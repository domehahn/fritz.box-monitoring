"""New-device watch -> Prometheus.

Polls ``fritz_device_up`` from Prometheus, keeps a **persistent** first-seen
timestamp per MAC (in the home_iot_data volume, so it survives Prometheus
restarts — which would otherwise make every device look new for a week), and
emits:

* ``device_first_seen_timestamp_seconds{mac,name}``
* ``device_known{mac,name} 1``      — MAC seen before / on the allowlist
* ``device_new{mac,name,ip,connection} 1`` — first seen < ``NETWATCH_NEW_DAYS`` ago
* ``netwatch_devices_total`` / ``netwatch_new_total`` / ``netwatch_up``

An optional allowlist file (one MAC or lowercase name-substring per line,
``#`` comments) marks devices known immediately.

:func:`decide` is pure.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_bool, env_float, env_str

INTERVAL_FLOOR_S = 30.0


@dataclass(frozen=True)
class NetwatchConfig:
    prom_url: str = "http://prometheus:9090"
    state_path: str = "/data/netwatch.json"
    allowlist_path: str = "/data/known_devices.txt"
    new_days: float = 7.0
    interval_seconds: float = 60.0
    #: on the very first run (no saved state), treat everything already
    #: connected as an established baseline instead of 50 "new device" alerts
    seed_baseline: bool = True

    @classmethod
    def from_env(cls) -> "NetwatchConfig":
        return cls(
            prom_url=env_str("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/"),
            state_path=env_str("NETWATCH_STATE_PATH", "/data/netwatch.json"),
            allowlist_path=env_str(
                "NETWATCH_ALLOWLIST_PATH", "/data/known_devices.txt"
            ),
            new_days=env_float("NETWATCH_NEW_DAYS", 7.0, floor=0.5),
            interval_seconds=env_float(
                "NETWATCH_INTERVAL_SECONDS", 60.0, floor=INTERVAL_FLOOR_S
            ),
            seed_baseline=env_bool("NETWATCH_SEED_BASELINE", True),
        )


@dataclass
class Device:
    mac: str
    name: str = ""
    ip: str = ""
    connection: str = ""  # "wifi" | "wired" | ""
    online: bool = False
    first_seen: float = 0.0
    allowlisted: bool = False


def load_allowlist(text: str) -> List[str]:
    out = []
    for line in text.splitlines():
        s = line.split("#", 1)[0].strip().lower()
        if s:
            out.append(s)
    return out


def _allowed(mac: str, name: str, allow: List[str]) -> bool:
    m, n = mac.lower(), name.lower()
    return any(a == m or (len(a) > 2 and a in n) for a in allow)


def decide(
    samples: List[Dict[str, str]],
    online_flags: List[float],
    state: Dict[str, float],
    allow: List[str],
    now: float,
    seed_ts: Optional[float] = None,
) -> Tuple[List[Device], Dict[str, float]]:
    """Merge a Prometheus ``fritz_device_up`` result with the saved first-seen
    map. Returns (devices, updated_state). ``state`` maps mac -> first_seen ts.

    If ``state`` is empty and ``seed_ts`` is given, unseen MACs are stamped at
    ``seed_ts`` (use a time outside the "new" window) so a fresh install treats
    everything already connected as a baseline instead of alerting on all of it.
    """
    new_state = dict(state)
    stamp = seed_ts if (not state and seed_ts is not None) else now
    by_mac: Dict[str, Device] = {}
    for metric, val in zip(samples, online_flags):
        mac = (metric.get("mac") or "").upper()
        if not mac:
            continue
        iface = (metric.get("interface") or "").lower()
        conn = "wifi" if "802.11" in iface or "wlan" in iface else (
            "wired" if iface else ""
        )
        d = by_mac.get(mac) or Device(mac=mac)
        d.name = d.name or metric.get("name", "")
        d.ip = d.ip or metric.get("ip", "")
        d.connection = d.connection or conn
        d.online = d.online or val > 0
        by_mac[mac] = d

    devices: List[Device] = []
    for mac, d in sorted(by_mac.items()):
        d.first_seen = new_state.setdefault(mac, stamp)
        d.allowlisted = _allowed(mac, d.name, allow)
        devices.append(d)
    return devices, new_state


class NetwatchExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.reg = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.reg)

        self.up = g("netwatch_up", "1 if the last Prometheus poll succeeded")
        self.total = g("netwatch_devices_total", "Distinct MACs known")
        self.new_total = g("netwatch_new_total", "MACs first seen within the window")
        self.first_seen = g(
            "device_first_seen_timestamp_seconds", "First time this MAC was seen",
            ("mac", "name"),
        )
        self.known = g("device_known", "1 if the MAC was seen before / allowlisted",
                       ("mac", "name"))
        self.new = g(
            "device_new", "1 if first seen within NETWATCH_NEW_DAYS",
            ("mac", "name", "ip", "connection"),
        )

    def update(self, devices: List[Device], *, ok: bool, new_days: float,
               now: float) -> None:
        self.up.set(1 if ok else 0)
        for m in (self.first_seen, self.known, self.new):
            m.clear()
        if not ok:
            return
        self.total.set(len(devices))
        cutoff = now - new_days * 86400
        n_new = 0
        for d in devices:
            self.first_seen.labels(d.mac, d.name).set(d.first_seen)
            recent = d.first_seen >= cutoff
            self.known.labels(d.mac, d.name).set(
                0 if (recent and not d.allowlisted) else 1
            )
            if recent and not d.allowlisted:
                n_new += 1
                self.new.labels(d.mac, d.name, d.ip, d.connection).set(1)
        self.new_total.set(n_new)

    def render(self) -> bytes:
        return generate_latest(self.reg)


def _read(path: str, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return default


def _load_state(path: str) -> Dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(_read(path, "{}")).items()}
    except (ValueError, AttributeError):
        return {}


def _save_state(path: str, state: Dict[str, float]) -> None:
    tmp = f"{path}.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
    except OSError as exc:  # pragma: no cover
        logger.warning("could not persist netwatch state: {}", exc)


def collect_sync(cfg: NetwatchConfig, exp: NetwatchExporter) -> None:
    now = time.time()
    try:
        r = requests.get(
            f"{cfg.prom_url}/api/v1/query",
            params={"query": "fritz_device_up"},
            timeout=15,
        )
        r.raise_for_status()
        res = r.json()["data"]["result"]
        samples = [x["metric"] for x in res]
        flags = [float(x["value"][1]) for x in res]
    except Exception as exc:  # noqa: BLE001
        logger.warning("netwatch poll failed: {}", exc)
        exp.update([], ok=False, new_days=cfg.new_days, now=now)
        return

    state = _load_state(cfg.state_path)
    allow = load_allowlist(_read(cfg.allowlist_path))
    seed_ts = (now - (cfg.new_days + 1) * 86400) if cfg.seed_baseline else None
    devices, new_state = decide(samples, flags, state, allow, now, seed_ts)
    if new_state != state:
        _save_state(cfg.state_path, new_state)
    exp.update(devices, ok=True, new_days=cfg.new_days, now=now)
    n_new = sum(
        1 for d in devices
        if not d.allowlisted and d.first_seen >= now - cfg.new_days * 86400
    )
    logger.info("netwatch ok: {} MAC(s), {} new", len(devices), n_new)


async def collect_once(cfg: NetwatchConfig, exp: NetwatchExporter) -> None:
    import asyncio

    await asyncio.to_thread(collect_sync, cfg, exp)
