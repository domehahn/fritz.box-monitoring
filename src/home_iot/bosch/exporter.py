"""Bosch Smart Home Controller -> Prometheus.

Talks to the **local** SHC REST API through :mod:`boschshcpy` using a client
certificate you pair once by pressing the button on the controller (see
``docs/smart-home-exporters.md``). No Bosch cloud.

Because the exact ``boschshcpy`` object surface shifts between releases, all the
fragile attribute access is confined to :func:`read_devices`; everything the
metrics are built from is the plain :class:`BoschDeviceView`, which
:func:`to_metric_rows` (pure, no I/O) consumes.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float, env_str

INTERVAL_FLOOR_S = 20.0

#: battery enum name -> (percent estimate, ok flag). boschshcpy exposes an
#: ordinal enum, not a percentage; this is the conventional mapping.
_BATTERY_LEVELS = {
    "OK": (100.0, 1),
    "GOOD": (100.0, 1),
    "LOW_BATTERY": (15.0, 0),
    "CRITICAL_LOW": (5.0, 0),
    "CRITICALLY_LOW_BATTERY": (5.0, 0),
    "NOT_AVAILABLE": (0.0, 1),
}


@dataclass(frozen=True)
class BoschConfig:
    host: str
    cert_file: str
    key_file: str
    interval_seconds: float = 60.0

    @property
    def configured(self) -> bool:
        return bool(self.host and self.cert_file and self.key_file)

    @classmethod
    def from_env(cls) -> "BoschConfig":
        return cls(
            host=env_str("BOSCH_SHC_HOST"),
            cert_file=env_str("BOSCH_SHC_CERT_FILE", "/certs/bosch-shc-cert.pem"),
            key_file=env_str("BOSCH_SHC_KEY_FILE", "/certs/bosch-shc-key.pem"),
            interval_seconds=env_float(
                "BOSCH_INTERVAL_SECONDS", 60.0, floor=INTERVAL_FLOOR_S
            ),
        )


@dataclass
class BoschDeviceView:
    id: str
    name: str
    model: str
    room: str
    available: int
    battery_percent: Optional[float] = None
    battery_ok: Optional[int] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    valve_percent: Optional[float] = None
    fault: int = 0


@dataclass
class BoschSnapshot:
    devices: List[BoschDeviceView] = field(default_factory=list)
    shc_version: str = ""
    shc_update_available: int = 0


def _f(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _battery(name: Optional[str]) -> tuple[Optional[float], Optional[int]]:
    if not name:
        return None, None
    return _BATTERY_LEVELS.get(str(name).upper(), (None, None))


def read_devices(session: Any) -> BoschSnapshot:
    """Extract a :class:`BoschSnapshot` from a live ``boschshcpy`` session."""
    snap = BoschSnapshot()
    info = getattr(session, "information", None)
    if info is not None:
        snap.shc_version = str(getattr(info, "version", "") or "")
        upd = str(
            getattr(info, "updateState", getattr(info, "update_state", ""))
        ).upper()
        snap.shc_update_available = (
            1 if upd in ("UPDATE_AVAILABLE", "UPDATE_IN_PROGRESS", "DOWNLOADING") else 0
        )

    for dev in getattr(session, "devices", []) or []:
        status = str(getattr(dev, "status", "") or "").upper()
        view = BoschDeviceView(
            id=str(getattr(dev, "id", "")),
            name=str(getattr(dev, "name", "") or getattr(dev, "id", "")),
            model=str(getattr(dev, "device_model", "") or ""),
            room=str(getattr(dev, "room_id", "") or ""),
            available=1 if status in ("AVAILABLE", "", "ONLINE") else 0,
        )
        bl = getattr(dev, "batterylevel", None)
        pct, ok = _battery(getattr(bl, "name", bl))
        view.battery_percent, view.battery_ok = pct, ok

        for svc in getattr(dev, "device_services", []) or []:
            sid = str(getattr(svc, "id", "")).lower()
            state = getattr(svc, "state", {}) or {}
            get = state.get if hasattr(state, "get") else (lambda *_: None)
            if "temperaturelevel" in sid:
                view.temperature_c = _f(get("temperature"))
            elif "humiditylevel" in sid:
                view.humidity_pct = _f(get("humidity"))
            elif sid in ("valvetapcontrol", "valve") or "valvetap" in sid:
                view.valve_percent = _f(get("position") or get("valvePosition"))
            if str(get("faults") or "").strip() or get("fault"):
                view.fault = 1
        snap.devices.append(view)
    return snap


class BoschExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.registry)

        self.up = g("bosch_shc_up", "1 if the last SHC scrape succeeded")
        self.configured = g("bosch_shc_configured", "1 if host + client cert are set")
        self.last_ts = g(
            "bosch_shc_last_scrape_timestamp_seconds", "Unix time of last scrape"
        )
        self.device_count = g("bosch_shc_device_count", "Devices known to the SHC")
        self.update_available = g(
            "bosch_shc_update_available", "1 if the SHC has a firmware update pending"
        )
        self.info = g("bosch_shc_info", "SHC identity", ("version",))
        self.battery_low_count = g(
            "bosch_shc_battery_low_count", "Devices reporting a low/critical battery"
        )
        self.fault_count = g("bosch_shc_fault_count", "Devices reporting a fault")

        lbl = ("device", "model", "room")
        self.available = g(
            "bosch_device_available", "1 if the device is reachable", lbl
        )
        self.battery_percent = g(
            "bosch_device_battery_percent", "Battery estimate (0-100)", lbl
        )
        self.battery_ok = g("bosch_device_battery_ok", "1 if battery is OK", lbl)
        self.temperature = g(
            "bosch_device_temperature_celsius", "Measured temperature", lbl
        )
        self.humidity = g(
            "bosch_device_humidity_percent", "Measured relative humidity", lbl
        )
        self.valve = g(
            "bosch_device_valve_percent", "Radiator valve position (0-100)", lbl
        )
        self.fault = g("bosch_device_fault", "1 if the device reports a fault", lbl)

    def update(
        self, snap: Optional[BoschSnapshot], *, configured: bool, ok: bool
    ) -> None:
        self.configured.set(1 if configured else 0)
        self.up.set(1 if ok else 0)
        self.last_ts.set(time.time())
        for m in (
            self.available,
            self.battery_percent,
            self.battery_ok,
            self.temperature,
            self.humidity,
            self.valve,
            self.fault,
            self.info,
        ):
            m.clear()
        if snap is None or not ok:
            return

        self.device_count.set(len(snap.devices))
        self.update_available.set(snap.shc_update_available)
        if snap.shc_version:
            self.info.labels(snap.shc_version).set(1)

        low = faults = 0
        for d in snap.devices:
            lbl = (d.name, d.model, d.room)
            self.available.labels(*lbl).set(d.available)
            if d.battery_percent is not None:
                self.battery_percent.labels(*lbl).set(d.battery_percent)
            if d.battery_ok is not None:
                self.battery_ok.labels(*lbl).set(d.battery_ok)
                low += 0 if d.battery_ok else 1
            if d.temperature_c is not None:
                self.temperature.labels(*lbl).set(d.temperature_c)
            if d.humidity_pct is not None:
                self.humidity.labels(*lbl).set(d.humidity_pct)
            if d.valve_percent is not None:
                self.valve.labels(*lbl).set(d.valve_percent)
            self.fault.labels(*lbl).set(d.fault)
            faults += d.fault
        self.battery_low_count.set(low)
        self.fault_count.set(faults)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def _open_session(cfg: BoschConfig) -> Any:
    from boschshcpy import SHCSession

    session = SHCSession(cfg.host, cfg.cert_file, cfg.key_file)
    session.authenticate()
    return session


def collect_sync(cfg: BoschConfig, exp: BoschExporter) -> None:
    if not cfg.configured:
        exp.update(None, configured=False, ok=False)
        return
    try:
        session = _open_session(cfg)
        snap = read_devices(session)
        exp.update(snap, configured=True, ok=True)
        logger.info("bosch ok: {} device(s)", len(snap.devices))
    except Exception as exc:  # noqa: BLE001
        exp.update(None, configured=True, ok=False)
        logger.warning("bosch scrape failed: {}", exc)


async def collect_once(cfg: BoschConfig, exp: BoschExporter) -> None:
    await asyncio.to_thread(collect_sync, cfg, exp)
