"""
Tests for Prometheus exporter
"""

import pytest
from fritz_monitoring.exporter import FritzBoxExporter


@pytest.fixture
def exporter():
    """Fixture for exporter"""
    return FritzBoxExporter()


def test_exporter_initialization(exporter):
    """Test exporter initialization"""
    assert exporter.registry is not None
    assert exporter.downstream_speed is not None
    assert exporter.upstream_speed is not None
    assert exporter.connected is not None


def test_export_connection_metrics(exporter):
    """Test exporting connection metrics"""
    metrics = {
        "timestamp": "2024-01-01T12:00:00",
        "connection": {
            "downstream_speed_mbs": 100,
            "upstream_speed_mbs": 50,
            "connected": True,
            "bytes_sent": 1000000,
            "bytes_received": 2000000,
        },
        "devices": {"device_count": 5},
        "wlan": {"associated_devices": 3},
        "system": {"uptime_seconds": 86400},
    }

    exporter.export(metrics)

    # Verify metrics were set
    assert exporter.downstream_speed._value.get() == 100
    assert exporter.upstream_speed._value.get() == 50
    assert exporter.connected._value.get() == 1


def test_get_metrics_returns_bytes(exporter):
    """Test that get_metrics returns bytes"""
    metrics_bytes = exporter.get_metrics()
    assert isinstance(metrics_bytes, bytes)
    assert b"fritzbox_" in metrics_bytes
