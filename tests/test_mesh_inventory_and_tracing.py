"""Unit tests for Mesh Inventory, Offline / Power-Loss Detection, and Tracing."""
from datetime import datetime, timezone
import pytest
from fritz_avm_client import Node, Device, WanStats
from fritz_monitoring.collector import MonitoringSnapshot, CollectorState
from fritz_monitoring.exporter.prometheus_exporter import FritzPrometheusExporter
from fritz_monitoring.tracer import trace_span, current_trace_id


def test_tracer_span_and_context():
    """Verify trace_span sets and restores thread-local trace_id and span_id."""
    assert current_trace_id() is None

    with trace_span("root_span", {"test_attr": "value"}) as root:
        tid = current_trace_id()
        assert tid is not None
        assert len(tid) == 32
        assert root["trace_id"] == tid

        with trace_span("child_span") as child:
            # Child must share root's trace_id
            assert current_trace_id() == tid
            assert child["trace_id"] == tid
            assert child["span_id"] != root["span_id"]

    assert current_trace_id() is None


def test_mesh_node_offline_power_state_detection():
    """Verify that when a repeater is unplugged from power, it is tracked as offline rather than disappearing."""
    exporter = FritzPrometheusExporter()
    now = datetime.now(timezone.utc)

    # Pass 1: Router + 2 Repeaters (Repeater-OG and Repeater-Garten)
    snap1 = MonitoringSnapshot(
        timestamp=now,
        wan=WanStats(is_connected=True),
        mesh_nodes=(
            Node(name="fritz.box", mac="00:11:22:33:44:55", is_router=True),
            Node(
                name="Repeater-OG",
                mac="AA:BB:CC:DD:EE:01",
                is_repeater=True,
                parent_node="fritz.box",
                extra={"active": True, "link_rx_kbps": 866000, "link_tx_kbps": 866000},
            ),
            Node(
                name="Repeater-Garten",
                mac="AA:BB:CC:DD:EE:02",
                is_repeater=True,
                parent_node="Repeater-OG",  # Multi-hop!
                extra={"active": True, "link_rx_kbps": 300000, "link_tx_kbps": 300000},
            ),
        ),
        devices=(
            Device(
                name="Phone",
                mac="11:22:33:44:55:66",
                is_active=True,
                connected_to="Repeater-Garten",
            ),
        ),
        collection_duration_seconds=0.2,
    )
    state1 = CollectorState(last_success=now, consecutive_failures=0)
    exporter.render_snapshot(snap1, state1)
    out1 = exporter.render().decode("utf-8")

    # In Pass 1: both repeaters are online
    assert 'fritz_node_up{mac="AA:BB:CC:DD:EE:01",name="Repeater-OG",type="repeater"} 1.0' in out1
    assert 'fritz_node_up{mac="AA:BB:CC:DD:EE:02",name="Repeater-Garten",type="repeater"} 1.0' in out1
    assert 'fritz_mesh_node_power_state{mac="AA:BB:CC:DD:EE:02",name="Repeater-Garten",state="online",type="repeater"} 1.0' in out1
    assert 'fritz_mesh_node_power_state{mac="AA:BB:CC:DD:EE:02",name="Repeater-Garten",state="offline",type="repeater"} 0.0' in out1
    # Multi-hop check: Garten is behind OG (hop 2)
    assert 'fritz_node_hop_count{mac="AA:BB:CC:DD:EE:02",name="Repeater-Garten",type="repeater"} 2.0' in out1

    # Pass 2: Repeater-Garten is pulled from the power socket (not present in mesh_nodes)
    snap2 = MonitoringSnapshot(
        timestamp=now,
        wan=WanStats(is_connected=True),
        mesh_nodes=(
            Node(name="fritz.box", mac="00:11:22:33:44:55", is_router=True),
            Node(
                name="Repeater-OG",
                mac="AA:BB:CC:DD:EE:01",
                is_repeater=True,
                parent_node="fritz.box",
                extra={"active": True, "link_rx_kbps": 866000, "link_tx_kbps": 866000},
            ),
        ),
        devices=(),
        collection_duration_seconds=0.2,
    )
    state2 = CollectorState(last_success=now, consecutive_failures=0)
    exporter.render_snapshot(snap2, state2)
    out2 = exporter.render().decode("utf-8")

    # Repeater-Garten MUST NOT disappear! It must report fritz_node_up 0.0 and power_state offline 1.0!
    assert 'fritz_node_up{mac="AA:BB:CC:DD:EE:02",name="Repeater-Garten",type="repeater"} 0.0' in out2
    assert 'fritz_mesh_node_present{mac="AA:BB:CC:DD:EE:02",model="Repeater-Garten",name="Repeater-Garten",type="repeater"} 1.0' in out2
    assert 'fritz_mesh_node_online{mac="AA:BB:CC:DD:EE:02",name="Repeater-Garten",type="repeater"} 0.0' in out2
    assert 'fritz_mesh_node_power_state{mac="AA:BB:CC:DD:EE:02",name="Repeater-Garten",state="offline",type="repeater"} 1.0' in out2
    assert 'fritz_mesh_node_power_state{mac="AA:BB:CC:DD:EE:02",name="Repeater-Garten",state="online",type="repeater"} 0.0' in out2
    assert 'fritz_mesh_node_last_seen_seconds{mac="AA:BB:CC:DD:EE:02",name="Repeater-Garten",type="repeater"}' in out2


def test_port_mapping_and_voip_rendering():
    """Verify that port forwardings and VoIP numbers are correctly exported."""
    from fritz_monitoring.collector import PortMappingEntry, VoipNumberInfo

    exporter = FritzPrometheusExporter()
    now = datetime.now(timezone.utc)

    snap = MonitoringSnapshot(
        timestamp=now,
        wan=WanStats(is_connected=True),
        port_mappings=(
            PortMappingEntry(
                external_port=8080,
                protocol="TCP",
                internal_client="192.168.178.50",
                internal_port=80,
                description="Webserver",
                enabled=True,
                lease_duration=0,
                is_upnp=False,
            ),
            PortMappingEntry(
                external_port=3074,
                protocol="UDP",
                internal_client="192.168.178.99",
                internal_port=3074,
                description="Xbox UPnP",
                enabled=True,
                lease_duration=3600,
                is_upnp=True,
            ),
        ),
        voip_numbers=(
            VoipNumberInfo(number="0123456789", is_registered=True),
        ),
        collection_duration_seconds=0.1,
    )
    exporter.render_snapshot(snap)
    out = exporter.render().decode("utf-8")

    assert "fritz_total_port_mappings 2.0" in out
    assert "fritz_upnp_port_mappings 1.0" in out
    assert 'description="Webserver",internal_client="192.168.178.50"' in out
    assert 'description="Xbox UPnP",internal_client="192.168.178.99",internal_port="3074",is_upnp="true"' in out
    assert "fritz_voip_total_numbers 1.0" in out
    assert "fritz_voip_registered_numbers 1.0" in out
    assert 'fritz_voip_number_registered{number="0123456789"} 1.0' in out

