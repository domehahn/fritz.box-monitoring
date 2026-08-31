"""Philips Hue Bridge -> Prometheus.

Talks to the **local** CLIP v2 API (``https://<bridge>/clip/v2/resource``) with a
``hue-application-key``. The bridge serves a self-signed certificate, so TLS
verification is off by default (``HUE_VERIFY_TLS=true`` plus ``HUE_CA_FILE`` to
pin it). No cloud, no account.

The single most useful signal here is ``hue_zigbee_connectivity_status``: it goes
to 0 the moment a bulb or accessory drops off the Zigbee mesh, which is how you
notice a dying bulb or a routing hole long before someone flips a switch.

Pure-ish core: :func:`parse_resources` turns the raw CLIP payloads into
:class:`HueSnapshot` without any I/O, so it is fully unit-testable.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
import urllib3
from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_bool, env_float, env_str, read_secret

INTERVAL_FLOOR_S = 15.0
HTTP_TIMEOUT_S = 8.0


@dataclass(frozen=True)
class HueConfig:
    bridge_host: str
    app_key: str
    verify_tls: bool = False
    ca_file: str = ""
    interval_seconds: float = 60.0

    @property
    def configured(self) -> bool:
        return bool(self.bridge_host and self.app_key)

    @classmethod
    def from_env(cls) -> "HueConfig":
        return cls(
            bridge_host=env_str("HUE_BRIDGE_HOST"),
            app_key=read_secret(env_str("HUE_APP_KEY")),
            verify_tls=env_bool("HUE_VERIFY_TLS", False),
            ca_file=env_str("HUE_CA_FILE"),
            interval_seconds=env_float(
                "HUE_INTERVAL_SECONDS", 60.0, floor=INTERVAL_FLOOR_S
            ),
        )


@dataclass
class HueDevice:
    rid: str
    name: str
    mac: str
    model: str
    archetype: str


@dataclass
class HueSnapshot:
    devices: Dict[str, HueDevice] = field(default_factory=dict)
    # rid of device -> connected(1) / issue(0)
    connectivity: Dict[str, int] = field(default_factory=dict)
    lights: List[Dict[str, Any]] = field(default_factory=list)
    batteries: List[Dict[str, Any]] = field(default_factory=list)
    temperatures: List[Dict[str, Any]] = field(default_factory=list)
    light_levels: List[Dict[str, Any]] = field(default_factory=list)
    motions: List[Dict[str, Any]] = field(default_factory=list)
    bridge_id: str = ""


def _owner(res: Dict[str, Any]) -> str:
    return ((res.get("owner") or {}).get("rid")) or ""


def parse_resources(raw: Dict[str, List[Dict[str, Any]]]) -> HueSnapshot:
    """Join the CLIP v2 resource lists into one :class:`HueSnapshot`.

    ``raw`` maps resource type (``device``, ``light``, ``zigbee_connectivity``,
    ``device_power``, ``temperature``, ``light_level``, ``motion``, ``bridge``)
    to the ``data`` array the bridge returned for it.
    """
    snap = HueSnapshot()

    for d in raw.get("device", []):
        meta = d.get("metadata") or {}
        pdata = d.get("product_data") or {}
        mac = ""
        for svc in d.get("services", []):
            if svc.get("rtype") == "zigbee_connectivity":
                mac = svc.get("rid", "")
        snap.devices[d.get("id", "")] = HueDevice(
            rid=d.get("id", ""),
            name=meta.get("name") or pdata.get("product_name") or d.get("id", ""),
            mac=mac,
            model=pdata.get("model_id") or "",
            archetype=meta.get("archetype") or pdata.get("product_archetype") or "",
        )

    for c in raw.get("zigbee_connectivity", []):
        status = (c.get("status") or "").lower()
        snap.connectivity[_owner(c)] = 1 if status == "connected" else 0

    snap.lights = raw.get("light", [])
    snap.batteries = raw.get("device_power", [])
    snap.temperatures = raw.get("temperature", [])
    snap.light_levels = raw.get("light_level", [])
    snap.motions = raw.get("motion", [])

    bridges = raw.get("bridge", [])
    if bridges:
        snap.bridge_id = bridges[0].get("bridge_id", "") or bridges[0].get("id", "")
    return snap


def _lux_from_level(level: float) -> float:
    """Hue reports illuminance as ``10000*log10(lux)+1``; invert it."""
    if level <= 0:
        return 0.0
    return round(math.pow(10, (level - 1) / 10000.0), 2)


class HueClient:
    """Thin synchronous CLIP v2 client."""

    RESOURCES = (
        "device",
        "zigbee_connectivity",
        "light",
        "device_power",
        "temperature",
        "light_level",
        "motion",
        "bridge",
    )

    def __init__(self, cfg: HueConfig) -> None:
        self.cfg = cfg
        self._s = requests.Session()
        self._s.headers.update({"hue-application-key": cfg.app_key})
        if cfg.verify_tls and cfg.ca_file:
            self._verify: Any = cfg.ca_file
        elif cfg.verify_tls:
            self._verify = True
        else:
            self._verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get(self, resource: str) -> List[Dict[str, Any]]:
        url = f"https://{self.cfg.bridge_host}/clip/v2/resource/{resource}"
        resp = self._s.get(url, timeout=HTTP_TIMEOUT_S, verify=self._verify)
        resp.raise_for_status()
        return resp.json().get("data", []) or []

    def fetch(self) -> Dict[str, List[Dict[str, Any]]]:
        return {r: self._get(r) for r in self.RESOURCES}


class HueExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.registry)

        self.up = g("hue_up", "1 if the last bridge scrape succeeded")
        self.configured = g("hue_configured", "1 if HUE_BRIDGE_HOST and key are set")
        self.scrape_seconds = g(
            "hue_scrape_duration_seconds", "Duration of the last scrape"
        )
        self.last_ts = g(
            "hue_last_scrape_timestamp_seconds", "Unix time of last scrape"
        )
        self.device_count = g(
            "hue_device_count", "Number of devices known to the bridge"
        )
        self.zigbee_issue_count = g(
            "hue_zigbee_issue_count", "Devices currently reporting Zigbee issues"
        )
        self.bridge_info = g("hue_bridge_info", "Bridge identity", ("bridge_id",))

        lbl = ("name", "model", "archetype")
        self.connectivity = g(
            "hue_zigbee_connectivity_status",
            "1 connected to the Zigbee mesh, 0 connection issues",
            lbl,
        )
        self.light_on = g("hue_light_on", "1 if the light is on", lbl)
        self.light_brightness = g(
            "hue_light_brightness_percent", "Light dimming level (0-100)", lbl
        )
        self.battery_percent = g(
            "hue_device_battery_percent", "Battery level (0-100)", lbl
        )
        self.battery_ok = g(
            "hue_device_battery_ok", "1 if battery_state is 'normal'", lbl
        )
        self.temperature = g(
            "hue_sensor_temperature_celsius", "Temperature sensor reading", lbl
        )
        self.light_level_raw = g(
            "hue_sensor_light_level_raw", "Raw Hue light_level value", lbl
        )
        self.light_level_lux = g(
            "hue_sensor_light_level_lux", "Derived illuminance in lux", lbl
        )
        self.motion = g("hue_sensor_motion", "1 if motion is currently detected", lbl)

    # -- update -------------------------------------------------------------
    def _labels_for(self, snap: HueSnapshot, owner_rid: str) -> Optional[tuple]:
        dev = snap.devices.get(owner_rid)
        if dev is None:
            return None
        return (dev.name, dev.model, dev.archetype)

    def update(
        self, snap: Optional[HueSnapshot], *, configured: bool, ok: bool, seconds: float
    ) -> None:
        self.configured.set(1 if configured else 0)
        self.up.set(1 if ok else 0)
        self.scrape_seconds.set(seconds)
        self.last_ts.set(time.time())
        for m in (
            self.connectivity,
            self.light_on,
            self.light_brightness,
            self.battery_percent,
            self.battery_ok,
            self.temperature,
            self.light_level_raw,
            self.light_level_lux,
            self.motion,
            self.bridge_info,
        ):
            m.clear()
        if snap is None or not ok:
            return

        self.device_count.set(len(snap.devices))
        if snap.bridge_id:
            self.bridge_info.labels(snap.bridge_id).set(1)

        issues = 0
        for rid, dev in snap.devices.items():
            if rid in snap.connectivity:
                val = snap.connectivity[rid]
                self.connectivity.labels(dev.name, dev.model, dev.archetype).set(val)
                issues += 0 if val else 1
        self.zigbee_issue_count.set(issues)

        for lt in snap.lights:
            labels = self._labels_for(snap, _owner(lt))
            if labels is None:
                continue
            on = 1 if ((lt.get("on") or {}).get("on")) else 0
            self.light_on.labels(*labels).set(on)
            dim = (lt.get("dimming") or {}).get("brightness")
            if dim is not None:
                self.light_brightness.labels(*labels).set(float(dim))

        for bp in snap.batteries:
            labels = self._labels_for(snap, _owner(bp))
            if labels is None:
                continue
            ps = bp.get("power_state") or {}
            lvl = ps.get("battery_level")
            if lvl is not None:
                self.battery_percent.labels(*labels).set(float(lvl))
            self.battery_ok.labels(*labels).set(
                1 if (ps.get("battery_state") or "").lower() == "normal" else 0
            )

        for tp in snap.temperatures:
            labels = self._labels_for(snap, _owner(tp))
            if labels is None:
                continue
            t = tp.get("temperature") or {}
            tval = t.get("temperature")
            if tval is None:
                tval = (t.get("temperature_report") or {}).get("temperature")
            if tval is not None:
                self.temperature.labels(*labels).set(float(tval))

        for ll in snap.light_levels:
            labels = self._labels_for(snap, _owner(ll))
            if labels is None:
                continue
            lv = ll.get("light") or {}
            raw = lv.get("light_level")
            if raw is None:
                raw = (lv.get("light_level_report") or {}).get("light_level")
            if raw is not None:
                self.light_level_raw.labels(*labels).set(float(raw))
                self.light_level_lux.labels(*labels).set(_lux_from_level(float(raw)))

        for mo in snap.motions:
            labels = self._labels_for(snap, _owner(mo))
            if labels is None:
                continue
            mv = mo.get("motion") or {}
            detected = mv.get("motion")
            if detected is None:
                detected = (mv.get("motion_report") or {}).get("motion")
            self.motion.labels(*labels).set(1 if detected else 0)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def collect_sync(cfg: HueConfig, exp: HueExporter) -> None:
    if not cfg.configured:
        exp.update(None, configured=False, ok=False, seconds=0.0)
        return
    start = time.perf_counter()
    try:
        raw = HueClient(cfg).fetch()
        snap = parse_resources(raw)
        exp.update(snap, configured=True, ok=True, seconds=time.perf_counter() - start)
        logger.info(
            "hue ok: {} devices, {} zigbee issue(s)",
            len(snap.devices),
            sum(1 for v in snap.connectivity.values() if v == 0),
        )
    except Exception as exc:  # noqa: BLE001
        exp.update(None, configured=True, ok=False, seconds=time.perf_counter() - start)
        logger.warning("hue scrape failed: {}", exc)


async def collect_once(cfg: HueConfig, exp: HueExporter) -> None:
    await asyncio.to_thread(collect_sync, cfg, exp)
