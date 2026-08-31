"""Derive structured network events from consecutive monitoring snapshots.

The FRITZ!Box device log (TR-064 ``DeviceInfo:GetDeviceLog`` /
``GetDeviceLogPath``) is **not reachable** with the least-privilege monitoring
account used here (401 Unauthorized), so events are *derived* from the state
transitions the collector already observes rather than read from the box.

Only transitions that can be reconstructed reliably from two snapshots are
emitted. Roaming, Wi-Fi channel changes and authentication failures are **not**
derivable today (they need the device log or per-client AP attribution) and are
intentionally absent instead of guessed.

The core (:func:`derive_events`) is a pure function over snapshot summaries so it
is fully unit-testable without a FRITZ!Box.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from .collector import MonitoringSnapshot


@dataclass(frozen=True)
class _DeviceState:
    mac: str
    name: str
    ip: str
    active: bool


@dataclass(frozen=True)
class _NodeState:
    mac: str
    name: str
    active: bool
    parent: str
    node_type: str = "repeater"  # router | repeater | powerline
    #: True for placeholder names the FRITZ!Box hands out to unconfigured /
    #: transient mesh entries — noisy, excluded from events.
    generic: bool = False


@dataclass(frozen=True)
class SnapshotSummary:
    """Minimal, hashable projection of a snapshot used for event derivation."""

    wan_connected: Optional[bool] = None
    wan_external_ip: Optional[str] = None
    wan_uptime: Optional[float] = None
    devices: Dict[str, _DeviceState] = field(default_factory=dict)
    nodes: Dict[str, _NodeState] = field(default_factory=dict)

    @classmethod
    def from_snapshot(cls, snap: MonitoringSnapshot) -> "SnapshotSummary":
        devices: Dict[str, _DeviceState] = {}
        for d in snap.devices:
            mac = (getattr(d, "mac", "") or "").upper()
            if not mac:
                continue
            devices[mac] = _DeviceState(
                mac=mac,
                name=getattr(d, "name", "") or "",
                ip=getattr(d, "ip", "") or "",
                active=bool(getattr(d, "is_active", False)),
            )
        nodes: Dict[str, _NodeState] = {}
        for n in snap.mesh_nodes:
            mac = (getattr(n, "mac", "") or "").upper()
            if not mac:
                continue
            extra = getattr(n, "extra", {}) or {}
            nodes[mac] = _NodeState(
                mac=mac,
                name=getattr(n, "name", "") or "",
                active=bool(extra.get("active", True)),
                parent=getattr(n, "parent_node", "") or "",
                node_type=getattr(n, "kind", "repeater"),
                generic=bool(getattr(n, "is_placeholder", False)),
            )
        wan = snap.wan
        return cls(
            wan_connected=getattr(wan, "is_connected", None) if wan else None,
            wan_external_ip=getattr(wan, "external_ip", None) if wan else None,
            wan_uptime=getattr(wan, "device_uptime", None) if wan else None,
            devices=devices,
            nodes=nodes,
        )


def _event(
    ts: datetime,
    event_type: str,
    subsystem: str,
    severity: str,
    message: str,
    **fields: Any,
) -> Dict[str, Any]:
    ev = {
        "timestamp": ts.astimezone(timezone.utc).isoformat(),
        "event_type": event_type,
        "subsystem": subsystem,
        "severity": severity,
        "message": message,
    }
    ev.update({k: v for k, v in fields.items() if v not in (None, "")})
    return ev


def derive_events(
    prev: Optional[SnapshotSummary],
    curr: SnapshotSummary,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Return the list of structured events implied by ``prev`` -> ``curr``.

    ``prev is None`` (first pass after start) yields no events: there is no
    baseline to diff against, so emitting "connected" for every client would be
    noise, not signal.
    """
    ts = now or datetime.now(timezone.utc)
    if prev is None:
        return []

    events: List[Dict[str, Any]] = []

    # --- WAN ---------------------------------------------------------------
    if prev.wan_connected is not None and curr.wan_connected is not None:
        if prev.wan_connected and not curr.wan_connected:
            events.append(
                _event(ts, "wan_disconnected", "wan", "critical", "WAN connection lost")
            )
        elif not prev.wan_connected and curr.wan_connected:
            events.append(
                _event(
                    ts,
                    "wan_connected",
                    "wan",
                    "info",
                    "WAN connection established",
                    external_ip=curr.wan_external_ip,
                )
            )
    if (
        prev.wan_external_ip
        and curr.wan_external_ip
        and prev.wan_external_ip != curr.wan_external_ip
    ):
        events.append(
            _event(
                ts,
                "wan_ip_changed",
                "wan",
                "info",
                "External IP changed",
                old_ip=prev.wan_external_ip,
                new_ip=curr.wan_external_ip,
            )
        )
    if (
        prev.wan_uptime is not None
        and curr.wan_uptime is not None
        and curr.wan_uptime + 30 < prev.wan_uptime
    ):
        events.append(
            _event(
                ts,
                "router_restart",
                "system",
                "warning",
                "Router uptime decreased - restart detected",
                uptime_seconds=curr.wan_uptime,
            )
        )

    # --- Mesh nodes ------------------------------------------------------
    for mac, cn in curr.nodes.items():
        if cn.generic:  # placeholder / transient entry — never a real event
            continue
        pn = prev.nodes.get(mac)
        if pn is None:
            if cn.active:
                events.append(
                    _event(
                        ts,
                        "node_connected",
                        "mesh",
                        "info",
                        f"Mesh node {cn.name} joined",
                        node=cn.name,
                        mac=mac,
                        parent=cn.parent,
                    )
                )
            continue
        if pn.active and not cn.active:
            events.append(
                _event(
                    ts,
                    "node_disconnected",
                    "mesh",
                    "warning",
                    f"Mesh node {cn.name} went down",
                    node=cn.name,
                    mac=mac,
                )
            )
        elif not pn.active and cn.active:
            events.append(
                _event(
                    ts,
                    "node_connected",
                    "mesh",
                    "info",
                    f"Mesh node {cn.name} came back",
                    node=cn.name,
                    mac=mac,
                    parent=cn.parent,
                )
            )
        # Powerline "parent" is a bus, not a tree, and the mesh JSON reports it
        # non-deterministically -> it oscillates every scrape. Only treat a
        # parent change on a Wi-Fi repeater as an event.
        if (
            cn.node_type == "repeater"
            and pn.parent
            and cn.parent
            and pn.parent != cn.parent
        ):
            events.append(
                _event(
                    ts,
                    "mesh_parent_changed",
                    "mesh",
                    "warning",
                    f"{cn.name} re-homed from {pn.parent} to {cn.parent}",
                    node=cn.name,
                    mac=mac,
                    old_parent=pn.parent,
                    new_parent=cn.parent,
                )
            )
    for mac, pn in prev.nodes.items():
        if mac not in curr.nodes and pn.active and not pn.generic:
            events.append(
                _event(
                    ts,
                    "node_disconnected",
                    "mesh",
                    "warning",
                    f"Mesh node {pn.name} disappeared from the mesh",
                    node=pn.name,
                    mac=mac,
                )
            )

    # --- Clients -------------------------------------------------------
    for mac, cd in curr.devices.items():
        pd = prev.devices.get(mac)
        if pd is None:
            if cd.active:
                events.append(
                    _event(
                        ts,
                        "client_connected",
                        "client",
                        "info",
                        f"{cd.name or mac} connected",
                        device=cd.name,
                        mac=mac,
                        ip=cd.ip,
                    )
                )
            continue
        if pd.active and not cd.active:
            events.append(
                _event(
                    ts,
                    "client_disconnected",
                    "client",
                    "info",
                    f"{cd.name or mac} disconnected",
                    device=cd.name,
                    mac=mac,
                    ip=pd.ip,
                )
            )
        elif not pd.active and cd.active:
            events.append(
                _event(
                    ts,
                    "client_connected",
                    "client",
                    "info",
                    f"{cd.name or mac} connected",
                    device=cd.name,
                    mac=mac,
                    ip=cd.ip,
                )
            )
    for mac, pd in prev.devices.items():
        if mac not in curr.devices and pd.active:
            events.append(
                _event(
                    ts,
                    "client_disconnected",
                    "client",
                    "info",
                    f"{pd.name or mac} disconnected",
                    device=pd.name,
                    mac=mac,
                    ip=pd.ip,
                )
            )

    return events


class EventDeriver:
    """Stateful wrapper: feed snapshots, get events logged as JSON lines.

    Log lines are emitted on the ``events`` logger channel as compact JSON so
    Grafana Alloy (already shipping this container's stdout to Loki) can index
    them with ``| json``. Only low-cardinality attributes belong in any future
    stream label; MAC / device name stay in the JSON body.
    """

    #: don't re-emit a mesh_parent_changed for the same node within this window
    PARENT_CHANGE_COOLDOWN_S = 900.0

    def __init__(self) -> None:
        self._prev: Optional[SnapshotSummary] = None
        self._last_parent_change: Dict[str, datetime] = {}

    def process(self, snapshot: MonitoringSnapshot) -> List[Dict[str, Any]]:
        curr = SnapshotSummary.from_snapshot(snapshot)
        events = derive_events(self._prev, curr, now=snapshot.timestamp)
        self._prev = curr

        # Debounce flappy mesh re-homing per node.
        kept: List[Dict[str, Any]] = []
        for ev in events:
            if ev["event_type"] == "mesh_parent_changed":
                mac = ev.get("mac", "")
                last = self._last_parent_change.get(mac)
                if (
                    last
                    and (snapshot.timestamp - last).total_seconds()
                    < self.PARENT_CHANGE_COOLDOWN_S
                ):
                    continue
                self._last_parent_change[mac] = snapshot.timestamp
            kept.append(ev)
        events = kept

        for ev in events:
            logger.bind(events=True).log(
                "WARNING" if ev["severity"] in ("warning", "critical") else "INFO",
                "fritz_event {}",
                json.dumps(ev, ensure_ascii=False, sort_keys=True),
            )
        return events
