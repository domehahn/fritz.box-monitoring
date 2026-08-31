"""FRITZ!DECT devices -> Prometheus.

Uses the same FRITZ!Box the main exporter already talks to, via
``fritzconnection``'s ``X_AVM-DE_Homeauto`` wrapper. Covered hardware: FRITZ!DECT
200/210 switchable sockets (power, energy, temperature), FRITZ!DECT 301/302
radiator controls (set / comfort temperature), and any DECT sensor exposing
temperature.

:func:`parse_devices` maps the raw ``New*`` dicts from
``get_device_information_list()`` to metric-ready records with the AVM unit
scaling already undone; it does no I/O.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float, env_str, read_secret

INTERVAL_FLOOR_S = 30.0


@dataclass(frozen=True)
class FritzDectConfig:
    host: str
    port: int
    username: str
    password: str
    use_tls: bool = False
    interval_seconds: float = 60.0

    @property
    def configured(self) -> bool:
        return bool(self.host and self.password)

    @classmethod
    def from_env(cls) -> "FritzDectConfig":
        return cls(
            host=env_str("FRITZ_HOST", "192.168.178.1"),
            port=int(env_str("FRITZ_PORT", "49000") or "49000"),
            username=env_str("FRITZ_USERNAME"),
            password=read_secret(
                env_str("FRITZ_PASSWORD_FILE") or env_str("FRITZ_PASSWORD")
            ),
            use_tls=env_str("FRITZ_USE_TLS", "false").lower() in ("1", "true", "yes"),
            interval_seconds=env_float(
                "FRITZDECT_INTERVAL_SECONDS", 60.0, floor=INTERVAL_FLOOR_S
            ),
        )


@dataclass
class DectDevice:
    ain: str
    name: str
    product: str
    present: int
    power_w: Optional[float] = None
    energy_wh: Optional[float] = None
    temperature_c: Optional[float] = None
    switch_on: Optional[int] = None
    hkr_set_c: Optional[float] = None
    hkr_comfort_c: Optional[float] = None
    hkr_valve_open: Optional[int] = None


def _num(d: Dict[str, Any], key: str) -> Optional[float]:
    raw = d.get(key)
    if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _hkr_temp(raw: Optional[float]) -> Optional[float]:
    """AVM HKR temps: 0.5 °C steps; 253=off, 254=on, else value/2."""
    if raw is None or raw in (253, 254):
        return None
    return raw / 2.0


def parse_devices(raw_list: List[Dict[str, Any]]) -> List[DectDevice]:
    out: List[DectDevice] = []
    for d in raw_list:
        power = _num(d, "NewMultimeterPower")
        energy = _num(d, "NewMultimeterEnergy")
        temp = _num(d, "NewTemperatureCelsius")
        switch = d.get("NewSwitchState")
        dev = DectDevice(
            ain=str(d.get("NewAIN", "")).strip(),
            name=str(d.get("NewDeviceName", "")).strip() or str(d.get("NewAIN", "")),
            product=str(d.get("NewProductName", "")).strip(),
            present=1
            if str(d.get("NewPresent", "")).strip() in ("1", "CONNECTED")
            else 0,
            power_w=None if power is None else round(power / 100.0, 2),
            energy_wh=energy,
            temperature_c=None if temp is None else round(temp / 10.0, 1),
            switch_on=None
            if switch in (None, "")
            else (1 if str(switch) in ("1", "ON") else 0),
            hkr_set_c=_hkr_temp(_num(d, "NewHkrSetTemperature")),
            hkr_comfort_c=_hkr_temp(_num(d, "NewHkrComfortTemperature")),
        )
        valve = _num(d, "NewHkrSetVentilStatus")
        if valve is not None:
            dev.hkr_valve_open = 1 if valve > 0 else 0
        out.append(dev)
    return out


class FritzDectExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.registry)

        self.up = g("fritzdect_up", "1 if the last homeauto scrape succeeded")
        self.configured = g("fritzdect_configured", "1 if FRITZ credentials are set")
        self.last_ts = g(
            "fritzdect_last_scrape_timestamp_seconds", "Unix time of last scrape"
        )
        self.device_count = g("fritzdect_device_count", "Number of DECT devices")

        lbl = ("ain", "name", "product")
        self.present = g(
            "fritzdect_device_present", "1 if the device is reachable", lbl
        )
        self.power = g("fritzdect_power_watts", "Current real power draw", lbl)
        self.energy = g(
            "fritzdect_energy_watt_hours_total",
            "Cumulative energy since first use",
            lbl,
        )
        self.temperature = g(
            "fritzdect_temperature_celsius", "Measured temperature", lbl
        )
        self.switch_on = g("fritzdect_switch_on", "1 if the socket output is on", lbl)
        self.hkr_set = g(
            "fritzdect_hkr_set_celsius", "Radiator target temperature", lbl
        )
        self.hkr_comfort = g(
            "fritzdect_hkr_comfort_celsius", "Radiator comfort temperature", lbl
        )
        self.hkr_valve = g(
            "fritzdect_hkr_valve_open", "1 if the radiator valve is open", lbl
        )

    def update(
        self, devices: Optional[List[DectDevice]], *, configured: bool, ok: bool
    ) -> None:
        self.configured.set(1 if configured else 0)
        self.up.set(1 if ok else 0)
        self.last_ts.set(time.time())
        for m in (
            self.present,
            self.power,
            self.energy,
            self.temperature,
            self.switch_on,
            self.hkr_set,
            self.hkr_comfort,
            self.hkr_valve,
        ):
            m.clear()
        if not ok or devices is None:
            return
        self.device_count.set(len(devices))
        for dev in devices:
            lbl = (dev.ain, dev.name, dev.product)
            self.present.labels(*lbl).set(dev.present)
            for value, metric in (
                (dev.power_w, self.power),
                (dev.energy_wh, self.energy),
                (dev.temperature_c, self.temperature),
                (dev.switch_on, self.switch_on),
                (dev.hkr_set_c, self.hkr_set),
                (dev.hkr_comfort_c, self.hkr_comfort),
                (dev.hkr_valve_open, self.hkr_valve),
            ):
                if value is not None:
                    metric.labels(*lbl).set(float(value))

    def render(self) -> bytes:
        return generate_latest(self.registry)


def _fetch(cfg: FritzDectConfig) -> List[Dict[str, Any]]:
    from fritzconnection.lib.fritzhomeauto import (  # type: ignore[import-untyped]
        FritzHomeAutomation,
    )

    fha = FritzHomeAutomation(
        address=cfg.host,
        port=cfg.port,
        user=cfg.username or None,
        password=cfg.password,
        use_tls=cfg.use_tls,
    )
    return fha.get_device_information_list()


def collect_sync(cfg: FritzDectConfig, exp: FritzDectExporter) -> None:
    if not cfg.configured:
        exp.update(None, configured=False, ok=False)
        return
    try:
        devices = parse_devices(_fetch(cfg))
        exp.update(devices, configured=True, ok=True)
        logger.info("fritzdect ok: {} device(s)", len(devices))
    except Exception as exc:  # noqa: BLE001
        exp.update(None, configured=True, ok=False)
        logger.warning("fritzdect scrape failed: {}", exc)


async def collect_once(cfg: FritzDectConfig, exp: FritzDectExporter) -> None:
    await asyncio.to_thread(collect_sync, cfg, exp)
