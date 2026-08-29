"""Unit tests for CollectorService and MonitoringSnapshot."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fritz_avm_client import (
    WanStats,
    DslStats,
    WlanStats,
    Node,
    Device,
    MeshTopology,
    Settings as FritzSettings,
)
from fritz_monitoring.collector import CollectorService, MonitoringSnapshot


def test_monitoring_snapshot_immutability():
    now = datetime.now(timezone.utc)
    snapshot = MonitoringSnapshot(timestamp=now, collection_duration_seconds=1.23)
    assert snapshot.timestamp == now
    assert snapshot.collection_duration_seconds == 1.23
    assert len(snapshot.mesh_nodes) == 0


def test_collector_service_collect_once():
    fritz_settings = FritzSettings(fritz_host="192.168.178.1")
    collector = CollectorService(fritz_settings=fritz_settings, interval_seconds=30)

    mock_client = MagicMock()
    mock_client.get_wan_stats_typed.return_value = WanStats(
        total_bytes_received=1000, total_bytes_sent=500
    )
    mock_client.router_client.get_dsl_stats.return_value = DslStats(
        downstream_attenuation=10.0
    )
    mock_client.wlan_client.get_wlan_traffic_stats.return_value = WlanStats(
        total_packets_sent=100
    )
    mock_client.discover_mesh.return_value = MeshTopology(
        nodes=(Node(name="Router", mac="00:11:22:33:44:55", is_router=True),),
        devices=(Device(name="Phone", mac="AA:BB:CC:DD:EE:FF", is_active=True),),
    )

    with patch.object(collector, "get_client", return_value=mock_client):
        snapshot = collector.collect_once()

        assert snapshot is not None
        assert snapshot.wan.total_bytes_received == 1000
        assert len(snapshot.mesh_nodes) == 1
        assert len(snapshot.devices) == 1

        state = collector.get_state()
        assert state.consecutive_failures == 0
        assert state.last_error_type is None
        assert state.last_success is not None
