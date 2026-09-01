"""Bosch Smart Home Controller -> Prometheus.

Talks to the **local** SHC REST API through :mod:`boschshcpy` using a client
certificate you pair once by pressing the button on the controller (see
``docs/smart-home-exporters.md``). No Bosch cloud.

Because the exact ``boschshcpy`` object surface shifts between releases, all the
fragile attribute access is confined to :func:`read_devices`; everything the
metrics are built from is the plain :class:`BoschDeviceView` / :class:`BoschSnapshot`.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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

#: air-quality / rating words -> 0 good, 1 medium, 2 bad
_RATING = {
    "GOOD": 0,
    "NORMAL": 0,
    "OK": 0,
    "MEDIUM": 1,
    "LITTLE_STUFFY": 1,
    "SLIGHTLY": 1,
    "BAD": 2,
    "HIGH": 2,
    "STUFFY": 2,
    "CRITICAL": 2,
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
    setpoint_c: Optional[float] = None
    power_w: Optional[float] = None
    energy_wh: Optional[float] = None
    switch_on: Optional[int] = None
    contact_open: Optional[int] = None
    air_purity_ppm: Optional[float] = None
    air_rating: Optional[int] = None
    smoke_alarm: Optional[int] = None
    fault: int = 0


@dataclass
class BoschSnapshot:
    devices: List[BoschDeviceView] = field(default_factory=list)
    shc_version: str = ""
    shc_update_available: int = 0
    intrusion_armed: Optional[int] = None
    intrusion_alarm: Optional[int] = None
    intrusion_available: Optional[int] = None
    #: surveillance system name -> 1 if alarm active
    surveillance: Dict[str, int] = field(default_factory=dict)


def _f(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _battery(name: Optional[str]) -> tuple[Optional[float], Optional[int]]:
    if not name:
        return None, None
    return _BATTERY_LEVELS.get(str(name).upper(), (None, None))


def _rating(word: Any) -> Optional[int]:
    if not word:
        return None
    return _RATING.get(str(word).upper())


def _rooms(session: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for r in getattr(session, "rooms", []) or []:
        rid = getattr(r, "id", None)
        if rid:
            out[str(rid)] = str(getattr(r, "name", rid) or rid)
    return out


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

    rooms = _rooms(session)

    for dev in getattr(session, "devices", []) or []:
        status = str(getattr(dev, "status", "") or "").upper()
        rid = str(getattr(dev, "room_id", "") or "")
        view = BoschDeviceView(
            id=str(getattr(dev, "id", "")),
            name=str(getattr(dev, "name", "") or getattr(dev, "id", "")),
            model=str(getattr(dev, "device_model", "") or ""),
            room=rooms.get(rid, rid),
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
            elif "valvetappet" in sid or "valvetap" in sid:
                view.valve_percent = _f(get("position") or get("valvePosition"))
            elif "roomclimatecontrol" in sid:
                view.setpoint_c = _f(get("setpointTemperature"))
            elif sid == "powermeter":
                view.power_w = _f(get("powerConsumption"))
                view.energy_wh = _f(get("energyConsumption"))
            elif sid in ("powerswitch", "binaryswitch"):
                sw = get("switchState") or get("on")
                view.switch_on = 1 if str(sw).upper() in ("ON", "TRUE", "1") else 0
            elif sid == "shuttercontact":
                view.contact_open = 1 if str(get("value")).upper() == "OPEN" else 0
            elif sid == "airqualitylevel":
                view.air_purity_ppm = _f(get("purity"))
                view.air_rating = _rating(get("combinedRating"))
                if view.temperature_c is None:
                    view.temperature_c = _f(get("temperature"))
                if view.humidity_pct is None:
                    view.humidity_pct = _f(get("humidity"))
            elif sid in ("smokedetectorcheck", "alarm"):
                val = str(get("value") or "").upper()
                if val:
                    view.smoke_alarm = (
                        0 if val in ("NONE", "IDLE_OFF", "OK", "SMOKE_TEST_OK") else 1
                    )
            if str(get("faults") or "").strip() or get("fault"):
                view.fault = 1
        snap.devices.append(view)

    # --- intrusion detection system --------------------------------------
    try:
        isys = getattr(session, "intrusion_system", None)
        if isys is not None:
            # boschshcpy hands these back as enums; str() is "ArmingState.FOO",
            # so match on substrings, not equality.
            arming = str(getattr(isys, "arming_state", "")).upper()
            alarm = str(getattr(isys, "alarm_state", "")).upper()
            snap.intrusion_armed = 0 if (not arming or "DISARM" in arming) else 1
            snap.intrusion_alarm = (
                1 if ("ALARM_ON" in alarm or "TRIGGER" in alarm) else 0
            )
            snap.intrusion_available = (
                1 if getattr(isys, "system_availability", True) else 0
            )
    except Exception as exc:  # noqa: BLE001 - optional subsystem
        logger.debug("intrusion system read failed: {}", exc)

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
        self.smoke_alarm_count = g(
            "bosch_shc_smoke_alarm_count", "Smoke detectors currently in alarm"
        )
        self.total_power = g(
            "bosch_shc_total_power_watts", "Sum of all plug power draw"
        )

        self.intrusion_armed = g(
            "bosch_intrusion_armed", "1 if the intrusion system is armed"
        )
        self.intrusion_alarm = g(
            "bosch_intrusion_alarm", "1 if the intrusion system is in alarm"
        )
        self.intrusion_available = g(
            "bosch_intrusion_available", "1 if the intrusion system is reachable"
        )
        self.surveillance = g(
            "bosch_surveillance_alarm",
            "1 if this surveillance system is in alarm",
            ("system",),
        )

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
        self.setpoint = g("bosch_device_setpoint_celsius", "Room climate setpoint", lbl)
        self.power = g(
            "bosch_device_power_watts", "Current real power draw (plugs)", lbl
        )
        self.energy = g(
            "bosch_device_energy_watt_hours_total", "Cumulative energy (plugs)", lbl
        )
        self.switch_on = g("bosch_device_switch_on", "1 if the plug output is on", lbl)
        self.contact_open = g(
            "bosch_device_contact_open", "1 if the door/window contact is open", lbl
        )
        self.air_purity = g(
            "bosch_device_air_purity_ppm", "TWINGUARD air purity (VOC ppm)", lbl
        )
        self.air_rating = g("bosch_device_air_rating", "0 good / 1 medium / 2 bad", lbl)
        self.smoke_alarm = g(
            "bosch_device_smoke_alarm", "1 if this detector is in alarm", lbl
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
            self.setpoint,
            self.power,
            self.energy,
            self.switch_on,
            self.contact_open,
            self.air_purity,
            self.air_rating,
            self.smoke_alarm,
            self.fault,
            self.info,
            self.surveillance,
        ):
            m.clear()
        if snap is None or not ok:
            return

        self.device_count.set(len(snap.devices))
        self.update_available.set(snap.shc_update_available)
        if snap.shc_version:
            self.info.labels(snap.shc_version).set(1)
        for k, v in (
            (self.intrusion_armed, snap.intrusion_armed),
            (self.intrusion_alarm, snap.intrusion_alarm),
            (self.intrusion_available, snap.intrusion_available),
        ):
            if v is not None:
                k.set(v)
        for name, alarm in snap.surveillance.items():
            self.surveillance.labels(name).set(alarm)

        low = faults = smoke = 0
        total_power = 0.0
        for d in snap.devices:
            lbl = (d.name, d.model, d.room)
            self.available.labels(*lbl).set(d.available)
            for value, metric in (
                (d.battery_percent, self.battery_percent),
                (d.temperature_c, self.temperature),
                (d.humidity_pct, self.humidity),
                (d.valve_percent, self.valve),
                (d.setpoint_c, self.setpoint),
                (d.power_w, self.power),
                (d.energy_wh, self.energy),
                (d.switch_on, self.switch_on),
                (d.contact_open, self.contact_open),
                (d.air_purity_ppm, self.air_purity),
                (d.air_rating, self.air_rating),
            ):
                if value is not None:
                    metric.labels(*lbl).set(float(value))
            if d.battery_ok is not None:
                self.battery_ok.labels(*lbl).set(d.battery_ok)
                low += 0 if d.battery_ok else 1
            if d.smoke_alarm is not None:
                self.smoke_alarm.labels(*lbl).set(d.smoke_alarm)
                smoke += d.smoke_alarm
            if d.power_w is not None:
                total_power += d.power_w
            self.fault.labels(*lbl).set(d.fault)
            faults += d.fault
        self.battery_low_count.set(low)
        self.fault_count.set(faults)
        self.smoke_alarm_count.set(smoke)
        self.total_power.set(total_power)

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
