"""
HTTP server for Prometheus exporter
"""

from aiohttp import web
from prometheus_client import generate_latest
from loguru import logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fritz_monitoring.exporter import FritzBoxExporter
    from fritz_monitoring.collector import FritzBoxCollector


class MetricsServer:
    """HTTP server for Prometheus metrics endpoint"""

    def __init__(self, exporter: "FritzBoxExporter", collector: "FritzBoxCollector"):
        """Initialize metrics server"""
        self.exporter = exporter
        self.collector = collector
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Setup HTTP routes"""
        self.app.router.add_get("/metrics", self.handle_metrics)
        self.app.router.add_get("/health", self.handle_health)

    async def handle_metrics(self, request: web.Request) -> web.Response:
        """Handle /metrics endpoint"""
        try:
            metrics = await self.collector.collect_metrics()
            self.exporter.export(metrics)
            return web.Response(
                text=self.exporter.get_metrics().decode("utf-8"),
                content_type="text/plain; charset=utf-8; version=0.0.4",
            )
        except Exception as e:
            logger.error(f"Error in metrics endpoint: {e}")
            self.exporter.scrape_errors.inc()
            return web.Response(status=500, text=str(e))

    async def handle_health(self, request: web.Request) -> web.Response:
        """Handle /health endpoint"""
        return web.Response(text="OK", status=200)

    async def start(self, host: str, port: int) -> None:
        """Start the metrics server"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f"Metrics server started on http://{host}:{port}")
