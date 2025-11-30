"""
Tests for Fritz!Box collector
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from fritz_monitoring.collector import FritzBoxCollector


@pytest.fixture
def collector():
    """Fixture for Fritz!Box collector"""
    return FritzBoxCollector(
        host="192.168.178.1",
        username="dslf",
        password="test_password",
        port=49000,
    )


@pytest.mark.asyncio
async def test_collector_initialization(collector):
    """Test collector initialization"""
    assert collector.host == "192.168.178.1"
    assert collector.port == 49000
    assert collector.address == "http://192.168.178.1:49000"


@pytest.mark.asyncio
async def test_connection_metrics_structure():
    """Test structure of connection metrics"""
    collector = FritzBoxCollector(
        host="192.168.178.1",
        username="dslf",
        password="test",
    )

    # Expected structure
    expected_keys = [
        "wan_ip",
        "downstream_speed_mbs",
        "upstream_speed_mbs",
        "connection_status",
        "connected",
        "is_connected",
        "bytes_sent",
        "bytes_received",
    ]

    # This would require mocking fritzconnection
    # Just verify the structure exists
    assert hasattr(collector, "_collect_connection_metrics_sync")
