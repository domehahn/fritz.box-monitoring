"""Unit tests for snapshot-derived network events."""
from datetime import datetime, timezone

from fritz_avm_client import Device, Node, WanStats

from fritz_monitoring.collector import MonitoringSnapshot
from fritz_monitoring.events import EventDeriver, SnapshotSummary, derive_events

NOW = datetime(2026, 8, 31, 20, 43, tzinfo=timezone.utc)


def snap(*, wan=None, nodes=(), devices=()):
    return MonitoringSnapshot(
        timestamp=NOW, wan=wan, mesh_nodes=tuple(nodes), devices=tuple(devices)
    )


def summ(**kw):
    return SnapshotSummary.from_snapshot(snap(**kw))


def types(events):
    return sorted(e["event_type"] for e in events)


def test_first_pass_emits_nothing():
    curr = summ(devices=[Device(name="A", mac="AA:AA:AA:AA:AA:AA", is_active=True)])
    assert derive_events(None, curr, NOW) == []


def test_no_change_emits_nothing():
    d = [Device(name="A", mac="AA:AA:AA:AA:AA:AA", is_active=True)]
    n = [Node(name="fritz.box", mac="00:00:00:00:00:01", is_router=True)]
    w = WanStats(is_connected=True, external_ip="1.2.3.4", device_uptime=1000)
    a = summ(wan=w, nodes=n, devices=d)
    b = summ(wan=w, nodes=n, devices=d)
    assert derive_events(a, b, NOW) == []


def test_client_connect_and_disconnect():
    mac = "AA:AA:AA:AA:AA:AA"
    off = summ(devices=[Device(name="Phone", mac=mac, is_active=False)])
    on = summ(
        devices=[Device(name="Phone", mac=mac, ip="192.168.178.9", is_active=True)]
    )
    assert types(derive_events(off, on, NOW)) == ["client_connected"]
    ev = derive_events(off, on, NOW)[0]
    assert (
        ev["mac"] == mac and ev["subsystem"] == "client" and ev["ip"] == "192.168.178.9"
    )
    assert types(derive_events(on, off, NOW)) == ["client_disconnected"]


def test_client_vanishing_from_list_counts_as_disconnect():
    mac = "AA:AA:AA:AA:AA:AA"
    before = summ(devices=[Device(name="Phone", mac=mac, is_active=True)])
    after = summ(devices=[])
    assert types(derive_events(before, after, NOW)) == ["client_disconnected"]


def test_node_down_and_parent_change():
    a = summ(
        nodes=[
            Node(name="fritz.box", mac="00:00:00:00:00:01", is_router=True),
            Node(
                name="Rep",
                mac="00:00:00:00:00:02",
                is_repeater=True,
                parent_node="fritz.box",
                extra={"active": True},
            ),
        ]
    )
    b = summ(
        nodes=[
            Node(name="fritz.box", mac="00:00:00:00:00:01", is_router=True),
            Node(
                name="Rep",
                mac="00:00:00:00:00:02",
                is_repeater=True,
                parent_node="fritz.box",
                extra={"active": False},
            ),
        ]
    )
    assert types(derive_events(a, b, NOW)) == ["node_disconnected"]

    c = summ(
        nodes=[
            Node(name="fritz.box", mac="00:00:00:00:00:01", is_router=True),
            Node(
                name="Rep",
                mac="00:00:00:00:00:02",
                is_repeater=True,
                parent_node="Rep2",
                extra={"active": True},
            ),
        ]
    )
    ev = derive_events(a, c, NOW)
    assert types(ev) == ["mesh_parent_changed"]
    assert ev[0]["old_parent"] == "fritz.box" and ev[0]["new_parent"] == "Rep2"


def test_wan_transitions():
    up = summ(
        wan=WanStats(is_connected=True, external_ip="1.1.1.1", device_uptime=5000)
    )
    down = summ(wan=WanStats(is_connected=False, device_uptime=5030))
    assert types(derive_events(up, down, NOW)) == ["wan_disconnected"]
    assert types(derive_events(down, up, NOW)) == ["wan_connected"]

    reip = summ(
        wan=WanStats(is_connected=True, external_ip="2.2.2.2", device_uptime=5100)
    )
    assert types(derive_events(up, reip, NOW)) == ["wan_ip_changed"]

    rebooted = summ(
        wan=WanStats(is_connected=True, external_ip="1.1.1.1", device_uptime=42)
    )
    assert "router_restart" in types(derive_events(up, rebooted, NOW))


def test_event_deriver_is_stateful_and_logs(caplog):
    dv = EventDeriver()
    mac = "AA:AA:AA:AA:AA:AA"
    assert dv.process(snap(devices=[Device(name="P", mac=mac, is_active=True)])) == []
    out = dv.process(snap(devices=[Device(name="P", mac=mac, is_active=False)]))
    assert types(out) == ["client_disconnected"]


def test_powerline_parent_flap_and_generic_nodes_are_suppressed():
    def node(mac, name, parent, is_pl=False):
        n = Node(
            name=name,
            mac=mac,
            is_repeater=not is_pl,
            is_powerline=is_pl,
            parent_node=parent,
            extra={"active": True},
        )
        return n

    a = summ(
        nodes=[
            node("00:00:00:00:00:01", "fritz.box", None),
            node("00:00:00:00:00:02", "PL-1", "fritz.box", is_pl=True),
            node("00:00:00:00:00:03", "fritz.repeater", "fritz.box"),  # generic
        ]
    )
    b = summ(
        nodes=[
            node("00:00:00:00:00:01", "fritz.box", None),
            node("00:00:00:00:00:02", "PL-1", "PL-2", is_pl=True),  # parent flapped
            node("00:00:00:00:00:03", "fritz.repeater", "PL-9"),  # generic flapped
        ]
    )
    # powerline parent flap + generic-node change -> nothing
    assert derive_events(a, b, NOW) == []


def test_event_deriver_debounces_repeater_parent_changes():
    dv = EventDeriver()
    mac = "00:00:00:00:00:AA"

    def snap_with_parent(parent):
        n = Node(
            name="Rep",
            mac=mac,
            is_repeater=True,
            parent_node=parent,
            extra={"active": True},
        )
        return snap(
            nodes=[Node(name="fritz.box", mac="00:00:00:00:00:01", is_router=True), n]
        )

    dv.process(snap_with_parent("fritz.box"))  # baseline
    out1 = dv.process(snap_with_parent("Rep-2"))  # real change -> 1 event
    assert types(out1) == ["mesh_parent_changed"]
    out2 = dv.process(snap_with_parent("fritz.box"))  # flaps back within cooldown
    assert out2 == []
