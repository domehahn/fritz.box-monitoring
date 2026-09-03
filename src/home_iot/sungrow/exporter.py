"""Sungrow hybrid inverter (SH-series) -> Prometheus, via the WiNet-S(2) local
WebSocket API — no cloud, no Modbus (the WiNet-S only allows one Modbus master
and iSolarCloud holds it).

Flow: ``wss://<host>/ws/home/overview`` -> ``connect`` (get token) ->
``login`` (read-only user) -> poll ``real`` for the inverter dev_id.

:func:`parse_real` is pure — it turns the WiNet-S ``real`` list (stable
``I18N_*`` data-name keys, string values with units) into a :class:`Reading`.
"""
from __future__ import annotations

import asyncio
import ssl
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float, env_str, read_secret

INTERVAL_FLOOR_S = 20.0
WS_PATH = "/ws/home/overview"

# WiNet-S "real" data-name -> (attr, scale to base unit). kW->W, kWh->Wh.
_FIELDS: Dict[str, tuple] = {
    "I18N_COMMON_TOTAL_DCPOWER": ("pv_power_w", 1000.0),
    "I18N_COMMON_TOTAL_ACTIVE_POWER": ("ac_power_w", 1000.0),
    "I18N_COMMON_FEED_NETWORK_TOTAL_ACTIVE_POWER": ("grid_export_power_w", 1000.0),
    "I18N_COMMON_LOAD_TOTAL_ACTIVE_POWER": ("load_power_w", 1000.0),
    "I18N_COMMON_PV_DAYILY_ENERGY_GENERATION": ("pv_yield_day_wh", 1000.0),
    "I18N_COMMON_PV_TOTAL_ENERGY_GENERATION": ("pv_yield_total_wh", 1000.0),
    "I18N_COMMON_DAILY_FEED_NETWORK_VOLUME": ("grid_export_day_wh", 1000.0),
    "I18N_COMMON_TOTAL_FEED_NETWORK_VOLUME": ("grid_export_total_wh", 1000.0),
    "I18N_COMMON_ENERGY_GET_FROM_GRID_DAILY": ("grid_import_day_wh", 1000.0),
    "I18N_COMMON_TOTAL_ELECTRIC_GRID_GET_POWER": ("grid_import_total_wh", 1000.0),
    "I18N_COMMON_DAILY_DIRECT_CONSUMPTION_ELECTRICITY_PV": ("self_cons_day_wh", 1000.0),
    "I18N_COMMON_TOTAL_DIRECT_POWER_CONSUMPTION_PV": ("self_cons_total_wh", 1000.0),
    "I18N_COMMON_AIR_TEM_INSIDE_MACHINE": ("temperature_c", 1.0),
    "I18N_COMMON_GRID_FREQUENCY": ("grid_hz", 1.0),
}


@dataclass(frozen=True)
class SungrowConfig:
    host: str = ""
    port: int = 443
    username: str = "user"
    password: str = "pw1111"
    interval_seconds: float = 30.0
    lang: str = "en_us"

    @property
    def configured(self) -> bool:
        return bool(self.host)

    @classmethod
    def from_env(cls) -> "SungrowConfig":
        return cls(
            host=env_str("SUNGROW_HOST"),
            port=int(env_float("SUNGROW_WS_PORT", 443.0)),
            username=env_str("SUNGROW_USERNAME", "user"),
            password=read_secret(env_str("SUNGROW_PASSWORD")) or "pw1111",
            interval_seconds=env_float(
                "SUNGROW_INTERVAL_SECONDS", 30.0, floor=INTERVAL_FLOOR_S
            ),
            lang=env_str("SUNGROW_LANG", "en_us"),
        )


@dataclass
class Reading:
    pv_power_w: Optional[float] = None
    ac_power_w: Optional[float] = None
    grid_export_power_w: Optional[float] = None
    load_power_w: Optional[float] = None
    pv_yield_day_wh: Optional[float] = None
    pv_yield_total_wh: Optional[float] = None
    grid_export_day_wh: Optional[float] = None
    grid_export_total_wh: Optional[float] = None
    grid_import_day_wh: Optional[float] = None
    grid_import_total_wh: Optional[float] = None
    self_cons_day_wh: Optional[float] = None
    self_cons_total_wh: Optional[float] = None
    temperature_c: Optional[float] = None
    grid_hz: Optional[float] = None
    running_state: str = ""

    # ---- derived -------------------------------------------------------- #
    @property
    def grid_power_w(self) -> Optional[float]:
        """Signed net grid power: positive = importing, negative = exporting."""
        if self.grid_export_power_w is None:
            return None
        return -self.grid_export_power_w

    @property
    def house_day_wh(self) -> Optional[float]:
        if self.grid_import_day_wh is None or self.self_cons_day_wh is None:
            return None
        return self.grid_import_day_wh + self.self_cons_day_wh

    @property
    def house_total_wh(self) -> Optional[float]:
        if self.grid_import_total_wh is None or self.self_cons_total_wh is None:
            return None
        return self.grid_import_total_wh + self.self_cons_total_wh


def _num(raw: str) -> Optional[float]:
    raw = (raw or "").strip()
    if raw in ("", "--", "---", "N/A"):
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_real(items: List[Dict[str, Any]]) -> Reading:
    """Turn the WiNet-S ``real`` service ``list`` into a :class:`Reading`."""
    r = Reading()
    for it in items or []:
        name = it.get("data_name", "")
        if name == "I18N_COMMON_RUNNING_STATE":
            r.running_state = str(it.get("data_value", "")).replace("I18N_COMMON_", "")
            continue
        spec = _FIELDS.get(name)
        if not spec:
            continue
        val = _num(str(it.get("data_value", "")))
        if val is None:
            continue
        attr, scale = spec
        setattr(r, attr, val * scale)
    return r


class SungrowExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.reg = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.reg)

        self.up = g("sungrow_up", "1 if the last WiNet-S poll succeeded")
        self.last_ts = g(
            "sungrow_last_scrape_timestamp_seconds", "Unix time of the last poll"
        )
        self.pv_power = g("sungrow_pv_power_watts", "PV (DC) power now")
        self.ac_power = g("sungrow_ac_power_watts", "Inverter AC output power now")
        self.load_power = g("sungrow_load_power_watts", "House load power now")
        self.grid_power = g(
            "sungrow_grid_power_watts", "Net grid power (+import / -export)"
        )
        self.grid_export_power = g(
            "sungrow_grid_export_power_watts", "Feed-in power now (+ = exporting)"
        )
        self.temp = g("sungrow_temperature_celsius", "Inverter internal temperature")
        self.hz = g("sungrow_grid_hertz", "Grid frequency")

        self.pv_day = g("sungrow_pv_yield_day_wh", "PV yield today")
        self.pv_total = g("sungrow_pv_yield_wh_total", "PV yield lifetime")
        self.imp_day = g("sungrow_grid_import_day_wh", "Grid import today")
        self.imp_total = g("sungrow_grid_import_wh_total", "Grid import lifetime")
        self.exp_day = g("sungrow_grid_export_day_wh", "Grid export today")
        self.exp_total = g("sungrow_grid_export_wh_total", "Grid export lifetime")
        self.self_day = g("sungrow_self_consumption_day_wh", "PV self-consumption today")
        self.self_total = g(
            "sungrow_self_consumption_wh_total", "PV self-consumption lifetime"
        )
        self.house_day = g(
            "sungrow_house_consumption_day_wh", "House consumption today (import + self)"
        )
        self.house_total = g(
            "sungrow_house_consumption_wh_total", "House consumption lifetime"
        )

        # mirror into the generic energy_* series the dashboards/rules already use
        self.e_power = g("energy_power_watts", "House load power", ("source",))
        self.e_import = g(
            "energy_import_watt_hours_total", "Grid import energy", ("source",)
        )

    def update(self, r: Optional[Reading], *, ok: bool) -> None:
        self.up.set(1 if ok else 0)
        self.last_ts.set(time.time())
        if not ok or r is None:
            return
        pairs = [
            (self.pv_power, r.pv_power_w), (self.ac_power, r.ac_power_w),
            (self.load_power, r.load_power_w), (self.grid_power, r.grid_power_w),
            (self.grid_export_power, r.grid_export_power_w),
            (self.temp, r.temperature_c), (self.hz, r.grid_hz),
            (self.pv_day, r.pv_yield_day_wh), (self.pv_total, r.pv_yield_total_wh),
            (self.imp_day, r.grid_import_day_wh),
            (self.imp_total, r.grid_import_total_wh),
            (self.exp_day, r.grid_export_day_wh),
            (self.exp_total, r.grid_export_total_wh),
            (self.self_day, r.self_cons_day_wh),
            (self.self_total, r.self_cons_total_wh),
            (self.house_day, r.house_day_wh), (self.house_total, r.house_total_wh),
        ]
        for gauge, val in pairs:
            if val is not None:
                gauge.set(val)
        if r.load_power_w is not None:
            self.e_power.labels("sungrow").set(r.load_power_w)
        if r.grid_import_total_wh is not None:
            self.e_import.labels("sungrow").set(r.grid_import_total_wh)

    def render(self) -> bytes:
        return generate_latest(self.reg)


class WiNetClient:
    """One long-lived WebSocket; reconnects + re-logs-in on failure."""

    def __init__(self, cfg: SungrowConfig) -> None:
        self.cfg = cfg
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._token = ""
        self._dev_id: Optional[str] = None

    @property
    def url(self) -> str:
        return f"wss://{self.cfg.host}:{self.cfg.port}{WS_PATH}"

    async def _rpc(self, service: str, **extra: Any) -> Dict[str, Any]:
        assert self._ws is not None
        payload = {"lang": self.cfg.lang, "token": self._token, "service": service}
        payload.update(extra)
        await self._ws.send_json(payload)
        msg = await asyncio.wait_for(self._ws.receive(), timeout=15)
        if msg.type != aiohttp.WSMsgType.TEXT:
            raise ConnectionError(f"ws closed while calling {service}")
        import json

        return json.loads(msg.data)

    async def connect(self) -> None:
        await self.close()
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(
            self.url, ssl=self._ctx, heartbeat=20
        )
        got = await self._rpc("connect")
        self._token = got.get("result_data", {}).get("token", "")
        li = await self._rpc(
            "login", username=self.cfg.username, passwd=self.cfg.password
        )
        if li.get("result_code") != 1:
            raise ConnectionError(f"WiNet-S login failed: {li.get('result_msg')}")
        self._token = li.get("result_data", {}).get("token", self._token)
        dl = await self._rpc("devicelist", type="0", is_check_token="0")
        devs = dl.get("result_data", {}).get("list", [])
        inv = next(
            (d for d in devs if int(d.get("dev_type", 0)) in (35, 21, 1)), devs[0]
        ) if devs else None
        self._dev_id = str(inv["dev_id"]) if inv else "1"
        logger.info(
            "WiNet-S connected: {} dev_id={}",
            inv.get("dev_model") if inv else "?", self._dev_id,
        )

    async def read(self) -> Reading:
        if self._ws is None or self._ws.closed:
            await self.connect()
        res = await self._rpc("real", dev_id=self._dev_id)
        code = res.get("result_code")
        if code == 201:  # rate limited — caller will retry next interval
            raise TimeoutError("WiNet-S busy (201)")
        if code != 1:
            # token likely expired; force a reconnect next time
            await self.close()
            raise ConnectionError(f"real failed: {res.get('result_msg')} ({code})")
        return parse_real(res.get("result_data", {}).get("list", []))

    async def close(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._ws = None
        self._session = None


async def collect_once(client: WiNetClient, exp: SungrowExporter) -> None:
    try:
        r = await client.read()
        exp.update(r, ok=True)
        logger.info(
            "sungrow ok: PV {:.0f} W, load {:.0f} W, grid {:+.0f} W, "
            "today import {:.1f} / export {:.1f} kWh",
            r.pv_power_w or 0, r.load_power_w or 0, r.grid_power_w or 0,
            (r.grid_import_day_wh or 0) / 1000, (r.grid_export_day_wh or 0) / 1000,
        )
    except Exception as exc:  # noqa: BLE001
        exp.update(None, ok=False)
        logger.warning("sungrow poll failed: {}", exc)
