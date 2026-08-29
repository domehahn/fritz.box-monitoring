"""Unit tests for FritzPrometheusExporter and MetricsServer health endpoints."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from aiohttp.test_utils import TestClient, TestServer

from fritz_avm_client import WanStats, DslStats, WlanStats, Node, Device
from fritz_monitoring.config import Settings
from fritz_monitoring.collector import (
    CollectorService,
    MonitoringSnapshot,
    CollectorState,
)
from fritz_monitoring.exporter.prometheus_exporter import FritzPrometheusExporter
from fritz_monitoring.exporter.server import MetricsServer


def test_exporter_render_snapshot():
    exporter = FritzPrometheusExporter()
    now = datetime.now(timezone.utc)
    snapshot = MonitoringSnapshot(
        timestamp=now,
        wan=WanStats(
            total_bytes_received=10000, total_bytes_sent=5000, is_connected=True
        ),
        dsl=DslStats(downstream_attenuation=12.5),
        wlan=WlanStats(total_packets_sent=50, total_packets_received=100),
        mesh_nodes=(Node(name="fritz.box", mac="00:11:22:33:44:55", is_router=True),),
        devices=(Device(name="Laptop", mac="AA:11:22:33:44:55", is_active=True),),
        collection_duration_seconds=0.45,
    )
    state = CollectorState(last_success=now, consecutive_failures=0)

    exporter.render_snapshot(snapshot, state)
    metrics_output = exporter.render().decode("utf-8")

    assert "fritz_scrape_success 1.0" in metrics_output
    assert "fritz_router_bytes_received_total 10000.0" in metrics_output
    assert "fritz_online_devices 1.0" in metrics_output


@pytest.mark.asyncio
async def test_metrics_server_endpoints():
    settings = Settings()
    mock_collector = MagicMock(spec=CollectorService)

    now = datetime.now(timezone.utc)
    mock_collector.get_snapshot.return_value = MonitoringSnapshot(
        timestamp=now,
        wan=WanStats(total_bytes_received=500),
    )
    mock_collector.get_state.return_value = CollectorState(
        last_success=now, consecutive_failures=0
    )

    server_obj = MetricsServer(settings, collector_service=mock_collector)
    test_server = TestServer(server_obj.app)
    client = TestClient(test_server)

    await client.start_server()
    try:
        # Liveness check
        resp_health = await client.get("/healthz")
        assert resp_health.status == 200
        text_health = await resp_health.text()
        assert text_health == "OK"

        # Readiness check
        resp_ready = await client.get("/readyz")
        assert resp_ready.status == 200

        # Metrics check
        resp_metrics = await client.get("/metrics")
        assert resp_metrics.status == 200
        metrics_text = await resp_metrics.text()
        assert "fritz_exporter_build_info" in metrics_text
    finally:
        await client.close()
