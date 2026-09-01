"""Electricity price + (optional) real household consumption -> Prometheus.

Price source, in order of preference:
  * **Tibber** (``TIBBER_TOKEN``) — consumer price incl. level + today/tomorrow.
  * **aWATTar** (``ENERGY_MARKET=awattar_de|awattar_at``) — hourly spot price,
    no key. A rough consumer price is derived as
    ``spot * ENERGY_VAT + ENERGY_SURCHARGE_CT_KWH/100``.

Consumption source (optional):
  * **Tibber** hourly ``consumption`` (last completed hour).
  * **Shelly EM / 3EM / Pro 3EM** at ``SHELLY_HOST`` — live power + energy.

Pure helpers (``awattar_slots``, ``price_stats``, ``parse_shelly``,
``parse_tibber``) are unit-tested without network.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float, env_str, read_secret

INTERVAL_FLOOR_S = 60.0
HTTP_TIMEOUT_S = 10.0
_AWATTAR = {
    "awattar_de": "https://api.awattar.de/v1/marketdata",
    "awattar_at": "https://api.awattar.at/v1/marketdata",
}
_TIBBER_URL = "https://api.tibber.com/v1-beta/gql"
_LEVELS = {
    "VERY_CHEAP": 0,
    "CHEAP": 1,
    "NORMAL": 2,
    "EXPENSIVE": 3,
    "VERY_EXPENSIVE": 4,
}


@dataclass(frozen=True)
class EnergyConfig:
    market: str = "awattar_de"
    vat: float = 1.19
    surcharge_ct_kwh: float = 0.0
    tibber_token: str = ""
    shelly_host: str = ""
    interval_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> "EnergyConfig":
        return cls(
            market=env_str("ENERGY_MARKET", "awattar_de"),
            vat=env_float("ENERGY_VAT", 1.19, floor=1.0),
            surcharge_ct_kwh=env_float("ENERGY_SURCHARGE_CT_KWH", 0.0),
            tibber_token=read_secret(env_str("TIBBER_TOKEN")),
            shelly_host=env_str("SHELLY_HOST"),
            interval_seconds=env_float(
                "ENERGY_INTERVAL_SECONDS", 120.0, floor=INTERVAL_FLOOR_S
            ),
        )


@dataclass
class PriceSnapshot:
    source: str = ""
    spot_eur_kwh: Optional[float] = None
    consumer_eur_kwh: Optional[float] = None
    level: Optional[int] = None
    rank_today: Optional[float] = None
    min_today: Optional[float] = None
    max_today: Optional[float] = None
    mean_today: Optional[float] = None
    min_next12h: Optional[float] = None


@dataclass
class MeterSnapshot:
    source: str = ""
    power_w: Optional[float] = None
    phase_w: Dict[str, float] = field(default_factory=dict)
    import_wh: Optional[float] = None
    export_wh: Optional[float] = None
    last_hour_kwh: Optional[float] = None
    last_hour_cost_eur: Optional[float] = None


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# --- aWATTar ---------------------------------------------------------------
def awattar_slots(payload: Dict[str, Any]) -> List[Dict[str, float]]:
    out = []
    for row in payload.get("data", []) or []:
        out.append(
            {
                "start": float(row["start_timestamp"]) / 1000.0,
                "end": float(row["end_timestamp"]) / 1000.0,
                "eur_kwh": float(row["marketprice"]) / 1000.0,  # Eur/MWh -> Eur/kWh
            }
        )
    return out


def price_stats(
    slots: List[Dict[str, float]], now: float, vat: float, surcharge_ct_kwh: float
) -> PriceSnapshot:
    snap = PriceSnapshot(source="awattar")
    if not slots:
        return snap
    day_start = (
        datetime.fromtimestamp(now, timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )
    today = [s for s in slots if day_start <= s["start"] < day_start + 86400]
    cur = next((s for s in slots if s["start"] <= now < s["end"]), None)
    fut = [s for s in slots if s["start"] >= now][:12]

    def consumer(spot: float) -> float:
        return round(spot * vat + surcharge_ct_kwh / 100.0, 5)

    if cur:
        snap.spot_eur_kwh = round(cur["eur_kwh"], 5)
        snap.consumer_eur_kwh = consumer(cur["eur_kwh"])
    if today:
        prices = sorted(s["eur_kwh"] for s in today)
        snap.min_today = round(prices[0], 5)
        snap.max_today = round(prices[-1], 5)
        snap.mean_today = round(sum(prices) / len(prices), 5)
        if cur and snap.max_today != snap.min_today:
            snap.rank_today = round(
                (cur["eur_kwh"] - snap.min_today) / (snap.max_today - snap.min_today), 3
            )
            snap.level = min(4, int(snap.rank_today * 5))
        elif cur:
            snap.rank_today = 0.0
            snap.level = 2
    if fut:
        snap.min_next12h = round(min(s["eur_kwh"] for s in fut), 5)
    return snap


# --- Tibber --------------------------------------------------------------
_TIBBER_QUERY = """
{ viewer { homes {
  currentSubscription { priceInfo {
    current { total energy tax level startsAt }
    today { total startsAt }
    tomorrow { total startsAt }
  } }
  consumption(resolution: HOURLY, last: 1) { nodes { consumption cost from } }
} } }
"""


def parse_tibber(
    gql: Dict[str, Any], now: float
) -> tuple[PriceSnapshot, MeterSnapshot]:
    price = PriceSnapshot(source="tibber")
    meter = MeterSnapshot(source="tibber")
    homes = ((gql.get("data") or {}).get("viewer") or {}).get("homes") or []
    if not homes:
        return price, meter
    home = homes[0]
    pi = (home.get("currentSubscription") or {}).get("priceInfo") or {}
    cur = pi.get("current") or {}
    price.consumer_eur_kwh = _f(cur.get("total"))
    price.spot_eur_kwh = _f(cur.get("energy"))
    price.level = _LEVELS.get(str(cur.get("level", "")).upper())

    def _totals(key: str) -> List[float]:
        vals = []
        for x in pi.get(key) or []:
            v = _f(x.get("total"))
            if v is not None:
                vals.append(v)
        return vals

    today = _totals("today")
    if today and price.consumer_eur_kwh is not None:
        price.min_today = round(min(today), 5)
        price.max_today = round(max(today), 5)
        price.mean_today = round(sum(today) / len(today), 5)
        if price.max_today != price.min_today:
            price.rank_today = round(
                (price.consumer_eur_kwh - price.min_today)
                / (price.max_today - price.min_today),
                3,
            )
    fut = _totals("tomorrow")
    if fut:
        price.min_next12h = round(min(fut), 5)

    nodes = (home.get("consumption") or {}).get("nodes") or []
    if nodes:
        n = nodes[-1]
        meter.last_hour_kwh = _f(n.get("consumption"))
        meter.last_hour_cost_eur = _f(n.get("cost"))
    return price, meter


# --- Shelly EM --------------------------------------------------------
def parse_shelly(status: Dict[str, Any]) -> MeterSnapshot:
    m = MeterSnapshot(source="shelly")
    # Gen2 RPC: em:0 / emdata:0
    em = status.get("em:0")
    emd = status.get("emdata:0")
    if em is not None:
        m.power_w = _f(em.get("total_act_power"))
        for ph in ("a", "b", "c"):
            v = _f(em.get(f"{ph}_act_power"))
            if v is not None:
                m.phase_w[ph.upper()] = v
        if emd is not None:
            m.import_wh = _f(emd.get("total_act"))
            m.export_wh = _f(emd.get("total_act_ret"))
        return m
    # Gen1: emeters[] / total_power
    emeters = status.get("emeters")
    if isinstance(emeters, list) and emeters:
        total = 0.0
        imp = 0.0
        for i, e in enumerate(emeters):
            p = _f(e.get("power")) or 0.0
            total += p
            m.phase_w[chr(ord("A") + i)] = p
            imp += _f(e.get("total")) or 0.0
        m.power_w = total
        m.import_wh = imp
        return m
    # Plain Gen1 plug
    if "total_power" in status:
        m.power_w = _f(status.get("total_power"))
    return m


# --- exporter ---------------------------------------------------------
class EnergyExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.registry)

        self.up = g("energy_up", "1 if a price was fetched")
        self.last_ts = g(
            "energy_last_scrape_timestamp_seconds", "Unix time of last poll"
        )
        self.price = g(
            "energy_price_eur_per_kwh",
            "Consumer price incl. VAT + surcharge",
            ("source",),
        )
        self.spot = g(
            "energy_spot_price_eur_per_kwh", "Raw day-ahead spot price", ("source",)
        )
        self.level = g(
            "energy_price_level", "0 very cheap .. 4 very expensive", ("source",)
        )
        self.rank = g(
            "energy_price_rank_today",
            "0 cheapest .. 1 priciest hour today",
            ("source",),
        )
        self.pmin = g(
            "energy_price_min_today_eur_per_kwh", "Cheapest hour today", ("source",)
        )
        self.pmax = g(
            "energy_price_max_today_eur_per_kwh", "Priciest hour today", ("source",)
        )
        self.pmean = g(
            "energy_price_mean_today_eur_per_kwh", "Mean price today", ("source",)
        )
        self.pfut = g(
            "energy_price_min_next12h_eur_per_kwh",
            "Cheapest of the next 12h",
            ("source",),
        )

        self.power = g("energy_power_watts", "Household real power", ("source",))
        self.phase = g(
            "energy_phase_power_watts", "Per-phase real power", ("source", "phase")
        )
        self.imp = g("energy_import_watt_hours_total", "Cumulative import", ("source",))
        self.exp = g(
            "energy_export_watt_hours_total", "Cumulative export / feed-in", ("source",)
        )
        self.hkwh = g(
            "energy_last_hour_kwh",
            "Consumption in the last completed hour",
            ("source",),
        )
        self.hcost = g(
            "energy_last_hour_cost_eur", "Cost of the last completed hour", ("source",)
        )

    def update(
        self,
        price: Optional[PriceSnapshot],
        meter: Optional[MeterSnapshot],
        *,
        ok: bool,
    ) -> None:
        self.up.set(1 if ok else 0)
        self.last_ts.set(time.time())
        for m in (
            self.price,
            self.spot,
            self.level,
            self.rank,
            self.pmin,
            self.pmax,
            self.pmean,
            self.pfut,
            self.power,
            self.phase,
            self.imp,
            self.exp,
            self.hkwh,
            self.hcost,
        ):
            m.clear()
        if price and ok:
            s = price.source or "?"
            for val, metric in (
                (price.consumer_eur_kwh, self.price),
                (price.spot_eur_kwh, self.spot),
                (price.level, self.level),
                (price.rank_today, self.rank),
                (price.min_today, self.pmin),
                (price.max_today, self.pmax),
                (price.mean_today, self.pmean),
                (price.min_next12h, self.pfut),
            ):
                if val is not None:
                    metric.labels(s).set(float(val))
        if meter and meter.source:
            s = meter.source
            for val, metric in (
                (meter.power_w, self.power),
                (meter.import_wh, self.imp),
                (meter.export_wh, self.exp),
                (meter.last_hour_kwh, self.hkwh),
                (meter.last_hour_cost_eur, self.hcost),
            ):
                if val is not None:
                    metric.labels(s).set(float(val))
            for ph, w in meter.phase_w.items():
                self.phase.labels(s, ph).set(w)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def _fetch_shelly(host: str) -> Optional[MeterSnapshot]:
    for path in ("/rpc/Shelly.GetStatus", "/status"):
        try:
            r = requests.get(f"http://{host}{path}", timeout=HTTP_TIMEOUT_S)
            r.raise_for_status()
            m = parse_shelly(r.json())
            if m.power_w is not None or m.phase_w:
                return m
        except Exception:  # noqa: BLE001
            continue
    return None


def _fetch_tibber(
    token: str, now: float
) -> tuple[Optional[PriceSnapshot], Optional[MeterSnapshot]]:
    r = requests.post(
        _TIBBER_URL,
        json={"query": _TIBBER_QUERY},
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    price, meter = parse_tibber(r.json(), now)
    return price, meter


def collect_sync(cfg: EnergyConfig, exp: EnergyExporter) -> None:
    now = time.time()
    price: Optional[PriceSnapshot] = None
    meter: Optional[MeterSnapshot] = None
    try:
        if cfg.tibber_token:
            try:
                price, meter = _fetch_tibber(cfg.tibber_token, now)
            except Exception as exc:  # noqa: BLE001
                logger.warning("tibber fetch failed: {}", exc)
        if price is None or price.consumer_eur_kwh is None:
            url = _AWATTAR.get(cfg.market, _AWATTAR["awattar_de"])
            r = requests.get(url, timeout=HTTP_TIMEOUT_S)
            r.raise_for_status()
            price = price_stats(
                awattar_slots(r.json()), now, cfg.vat, cfg.surcharge_ct_kwh
            )
        if cfg.shelly_host:
            sm = _fetch_shelly(cfg.shelly_host)
            if sm is not None:
                meter = sm
        ok = price is not None and price.consumer_eur_kwh is not None
        exp.update(price, meter, ok=ok)
        if ok:
            logger.info(
                "energy ok: {:.4f} €/kWh ({}), rank {}",
                price.consumer_eur_kwh,
                price.source,
                price.rank_today if price.rank_today is not None else "?",
            )
        else:
            logger.warning("energy: no usable price")
    except Exception as exc:  # noqa: BLE001
        exp.update(None, None, ok=False)
        logger.warning("energy poll failed: {}", exc)


async def collect_once(cfg: EnergyConfig, exp: EnergyExporter) -> None:
    await asyncio.to_thread(collect_sync, cfg, exp)
