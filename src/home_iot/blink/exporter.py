"""Blink cameras -> Prometheus.

Blink has **no local API** — this goes through Amazon's cloud with the
unofficial :mod:`blinkpy`. It is the most fragile of the four exporters: it needs
an Amazon account, a one-time 2FA code on first run, and it is cloud
rate-limited, so the poll interval floors at 5 minutes. Treat its numbers as
"best effort".

First run: set ``BLINK_USERNAME`` / ``BLINK_PASSWORD`` and ``BLINK_2FA_KEY`` with
the code Amazon e-mails/texts; blinkpy then writes a reusable token to
``BLINK_CREDENTIALS_FILE`` and the 2FA key is no longer needed.

:func:`to_metric_rows` is pure: it turns the ``{name: attributes}`` dicts
``blinkpy`` exposes into metric records without touching the network.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float, env_str

INTERVAL_FLOOR_S = 300.0

_BATTERY_STATE = {"ok": 1, "good": 1, "low": 0, "critical": 0}


@dataclass(frozen=True)
class BlinkConfig:
    username: str
    password: str
    credentials_file: str = "/data/blink.json"
    twofa_key: str = ""
    interval_seconds: float = 600.0

    @property
    def configured(self) -> bool:
        has_token = bool(self.credentials_file) and os.path.isfile(
            self.credentials_file
        )
        return (bool(self.username) and bool(self.password)) or has_token

    @classmethod
    def from_env(cls) -> "BlinkConfig":
        return cls(
            username=env_str("BLINK_USERNAME"),
            password=env_str("BLINK_PASSWORD"),
            credentials_file=env_str("BLINK_CREDENTIALS_FILE", "/data/blink.json"),
            twofa_key=env_str("BLINK_2FA_KEY"),
            interval_seconds=env_float(
                "BLINK_INTERVAL_SECONDS", 600.0, floor=INTERVAL_FLOOR_S
            ),
        )


@dataclass
class BlinkCameraView:
    name: str
    network: str
    battery_ok: Optional[int] = None
    battery_voltage_mv: Optional[float] = None
    temperature_c: Optional[float] = None
    wifi_strength: Optional[float] = None
    motion_enabled: Optional[int] = None
    motion_detected: Optional[int] = None


@dataclass
class BlinkSnapshot:
    cameras: List[BlinkCameraView] = field(default_factory=list)
    # sync module name -> online(1)/offline(0)
    sync_modules: Dict[str, int] = field(default_factory=dict)


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _b(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, str):
        return 1 if v.lower() in ("true", "on", "armed", "1", "yes") else 0
    return 1 if v else 0


def _f2c(f: Optional[float]) -> Optional[float]:
    return None if f is None else round((f - 32.0) * 5.0 / 9.0, 1)


def to_metric_rows(
    cameras: Dict[str, Dict[str, Any]],
    syncs: Dict[str, Dict[str, Any]],
) -> BlinkSnapshot:
    snap = BlinkSnapshot()
    for name, a in (cameras or {}).items():
        temp_c = _f(a.get("temperature_c"))
        if temp_c is None:
            temp_c = _f2c(_f(a.get("temperature")))
        snap.cameras.append(
            BlinkCameraView(
                name=str(a.get("name") or name),
                network=str(a.get("network_id") or a.get("sync_module") or ""),
                battery_ok=_BATTERY_STATE.get(str(a.get("battery") or "").lower()),
                battery_voltage_mv=_f(a.get("battery_voltage")),
                temperature_c=temp_c,
                wifi_strength=_f(a.get("wifi_strength") or a.get("signal_strength")),
                motion_enabled=_b(a.get("motion_enabled")),
                motion_detected=_b(a.get("motion_detected")),
            )
        )
    for name, a in (syncs or {}).items():
        status = str(a.get("status") or "").lower()
        snap.sync_modules[name] = 1 if status in ("online", "onboarded", "") else 0
    return snap


class BlinkExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.registry)

        self.up = g("blink_up", "1 if the last Blink cloud refresh succeeded")
        self.configured = g("blink_configured", "1 if Blink credentials are present")
        self.last_ts = g(
            "blink_last_scrape_timestamp_seconds", "Unix time of last scrape"
        )
        self.camera_count = g("blink_camera_count", "Number of cameras on the account")
        self.sync_online = g(
            "blink_sync_module_online", "1 if the sync module is online", ("name",)
        )

        lbl = ("camera", "network")
        self.battery_ok = g("blink_camera_battery_ok", "1 if battery state is OK", lbl)
        self.battery_voltage = g(
            "blink_camera_battery_millivolts", "Reported battery voltage (mV)", lbl
        )
        self.temperature = g(
            "blink_camera_temperature_celsius", "Camera temperature", lbl
        )
        self.wifi = g(
            "blink_camera_wifi_strength",
            "Wi-Fi signal strength (bars/dBm as reported)",
            lbl,
        )
        self.motion_enabled = g(
            "blink_camera_motion_enabled", "1 if motion detection is armed", lbl
        )
        self.motion_detected = g(
            "blink_camera_motion_detected", "1 if motion is currently flagged", lbl
        )

    def update(
        self, snap: Optional[BlinkSnapshot], *, configured: bool, ok: bool
    ) -> None:
        self.configured.set(1 if configured else 0)
        self.up.set(1 if ok else 0)
        self.last_ts.set(time.time())
        for m in (
            self.sync_online,
            self.battery_ok,
            self.battery_voltage,
            self.temperature,
            self.wifi,
            self.motion_enabled,
            self.motion_detected,
        ):
            m.clear()
        if snap is None or not ok:
            return
        self.camera_count.set(len(snap.cameras))
        for name, online in snap.sync_modules.items():
            self.sync_online.labels(name).set(online)
        for c in snap.cameras:
            lbl = (c.name, c.network)
            for value, metric in (
                (c.battery_ok, self.battery_ok),
                (c.battery_voltage_mv, self.battery_voltage),
                (c.temperature_c, self.temperature),
                (c.wifi_strength, self.wifi),
                (c.motion_enabled, self.motion_enabled),
                (c.motion_detected, self.motion_detected),
            ):
                if value is not None:
                    metric.labels(*lbl).set(float(value))

    def render(self) -> bytes:
        return generate_latest(self.registry)


async def _refresh(cfg: BlinkConfig) -> BlinkSnapshot:
    from aiohttp import ClientSession
    from blinkpy.auth import Auth  # type: ignore[import-untyped]
    from blinkpy.blinkpy import Blink  # type: ignore[import-untyped]
    from blinkpy.helpers.util import json_load  # type: ignore[import-untyped]

    session = ClientSession()
    try:
        blink = Blink(session=session)
        creds = None
        if cfg.credentials_file:
            try:
                creds = await json_load(cfg.credentials_file)
            except Exception:  # noqa: BLE001 - no token yet, fall back to user/pass
                creds = None
        if creds:
            blink.auth = Auth(creds, no_prompt=True, session=session)
        else:
            blink.auth = Auth(
                {"username": cfg.username, "password": cfg.password},
                no_prompt=True,
                session=session,
            )
        await blink.start()
        if cfg.twofa_key and not blink.available:
            await blink.auth.send_auth_key(blink, cfg.twofa_key)
            await blink.setup_post_verify()
        await blink.refresh(force=True)
        if cfg.credentials_file:
            try:
                await blink.save(cfg.credentials_file)
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not persist Blink token: {}", exc)

        cameras = {
            n: dict(getattr(c, "attributes", {}) or {})
            for n, c in blink.cameras.items()
        }
        syncs = {}
        for n, s in (getattr(blink, "sync", {}) or {}).items():
            syncs[n] = dict(getattr(s, "attributes", {}) or {})
        return to_metric_rows(cameras, syncs)
    finally:
        await session.close()


async def collect_once(cfg: BlinkConfig, exp: BlinkExporter) -> None:
    if not cfg.configured:
        exp.update(None, configured=False, ok=False)
        return
    try:
        snap = await _refresh(cfg)
        exp.update(snap, configured=True, ok=True)
        logger.info("blink ok: {} camera(s)", len(snap.cameras))
    except Exception as exc:  # noqa: BLE001
        exp.update(None, configured=True, ok=False)
        logger.warning("blink refresh failed: {}", exc)
