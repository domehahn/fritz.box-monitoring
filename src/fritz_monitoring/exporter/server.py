"""Async HTTP Metrics Server with /healthz, /readyz, and /metrics endpoints."""
import asyncio
from typing import Optional
from datetime import datetime, timezone
from aiohttp import web
from loguru import logger

from fritz_avm_client import Settings as FritzSettings
from ..collector import CollectorService
from ..config import Settings
from .prometheus_exporter import FritzPrometheusExporter


class MetricsServer:
    """HTTP web server serving Prometheus metrics and health endpoints."""

    def __init__(
        self, settings: Settings, collector_service: Optional[CollectorService] = None
    ) -> None:
        self.settings = settings
        fritz_settings = FritzSettings(
            fritz_host=settings.fritz_host,
            fritz_port=settings.fritz_port,
            fritz_username=settings.fritz_username,
            fritz_password=settings.resolved_password,
            fritz_password_file=settings.fritz_password_file,
            fritz_use_tls=settings.fritz_use_tls,
            fritz_timeout=settings.fritz_timeout,
        )

        if collector_service is None:
            self.collector_service = CollectorService(
                fritz_settings=fritz_settings,
                interval_seconds=settings.exporter_collection_interval,
            )
        else:
            self.collector_service = collector_service

        self.exporter = FritzPrometheusExporter(
            collector_service=self.collector_service
        )
        self.app = web.Application()
        self.app.add_routes(
            [
                web.get("/metrics", self.handle_metrics),
                web.get("/healthz", self.handle_healthz),
                web.get("/readyz", self.handle_readyz),
            ]
        )

    async def handle_metrics(self, request: web.Request) -> web.Response:
        """Endpoint serving Prometheus metrics."""
        return web.Response(
            body=self.exporter.render(),
            content_type="text/plain",
            charset="utf-8",
        )

    async def handle_healthz(self, request: web.Request) -> web.Response:
        """Liveness endpoint (returns 200 OK if exporter process is running)."""
        return web.Response(
            text="OK",
            content_type="text/plain",
            status=200,
        )

    async def handle_readyz(self, request: web.Request) -> web.Response:
        """Readiness endpoint (returns 200 OK if fresh snapshot exists, 503 otherwise)."""
        snapshot = self.collector_service.get_snapshot()
        state = self.collector_service.get_state()

        if snapshot is None or state.last_success is None:
            return web.Response(
                text="Service Unavailable: No snapshot collected yet",
                content_type="text/plain",
                status=503,
            )

        now = datetime.now(timezone.utc)
        age = (now - state.last_success).total_seconds()
        max_age = self.settings.exporter_ready_max_age

        if age > max_age:
            return web.Response(
                text=f"Service Unavailable: Snapshot age ({age:.1f}s) exceeds threshold ({max_age:.1f}s)",
                content_type="text/plain",
                status=503,
            )

        return web.Response(
            text=f"OK (Snapshot age: {age:.1f}s)",
            content_type="text/plain",
            status=200,
        )

    async def run(self) -> None:
        """Start the metrics server and background collector."""
        self.collector_service.start()
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(
            runner, self.settings.exporter_host, self.settings.exporter_port
        )
        await site.start()
        logger.info(
            f"Serving metrics on http://{self.settings.exporter_host}:{self.settings.exporter_port}/metrics"
        )
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            self.collector_service.stop()
