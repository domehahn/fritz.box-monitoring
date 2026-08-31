"""Local weather -> Prometheus.

Source: Bright Sky (``https://api.brightsky.dev``), a free, key-less JSON API
serving Deutscher Wetterdienst (DWD) observations. Set ``WEATHER_LAT`` /
``WEATHER_LON`` (or ``WEATHER_STATION`` = a DWD station id) in
``.env.production``.

Purpose: overlay outside conditions on heating (valve % vs outside temp =
degree-day view), on Wi-Fi/repeater behaviour, and on any future PV yield.

:func:`parse_current` is pure — it maps one Bright Sky ``weather`` object to the
metric values with no I/O.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float, env_str

INTERVAL_FLOOR_S = 300.0
HTTP_TIMEOUT_S = 10.0
API = "https://api.brightsky.dev/current_weather"


@dataclass(frozen=True)
class WeatherConfig:
    lat: str
    lon: str
    station: str
    interval_seconds: float = 300.0

    @property
    def configured(self) -> bool:
        return bool(self.station) or bool(self.lat and self.lon)

    @property
    def params(self) -> Dict[str, str]:
        if self.station:
            return {"dwd_station_id": self.station}
        return {"lat": self.lat, "lon": self.lon}

    @classmethod
    def from_env(cls) -> "WeatherConfig":
        return cls(
            lat=env_str("WEATHER_LAT"),
            lon=env_str("WEATHER_LON"),
            station=env_str("WEATHER_STATION"),
            interval_seconds=env_float(
                "WEATHER_INTERVAL_SECONDS", 300.0, floor=INTERVAL_FLOOR_S
            ),
        )


@dataclass
class WeatherReading:
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    wind_gust_kmh: Optional[float] = None
    precipitation_mm: Optional[float] = None
    cloud_cover_pct: Optional[float] = None
    pressure_hpa: Optional[float] = None
    solar_kwh_m2: Optional[float] = None
    visibility_m: Optional[float] = None
    condition: str = ""
    icon: str = ""


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def parse_current(weather: Dict[str, Any]) -> WeatherReading:
    return WeatherReading(
        temperature_c=_f(weather.get("temperature")),
        humidity_pct=_f(weather.get("relative_humidity")),
        wind_speed_kmh=_f(weather.get("wind_speed_10") or weather.get("wind_speed")),
        wind_gust_kmh=_f(
            weather.get("wind_gust_speed_10") or weather.get("wind_gust_speed")
        ),
        precipitation_mm=_f(
            weather.get("precipitation_10") or weather.get("precipitation")
        ),
        cloud_cover_pct=_f(weather.get("cloud_cover")),
        pressure_hpa=_f(weather.get("pressure_msl")),
        solar_kwh_m2=_f(weather.get("solar_10") or weather.get("solar")),
        visibility_m=_f(weather.get("visibility")),
        condition=str(weather.get("condition") or ""),
        icon=str(weather.get("icon") or ""),
    )


class WeatherExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.registry)

        self.up = g("weather_up", "1 if the last Bright Sky fetch succeeded")
        self.configured = g("weather_configured", "1 if a location/station is set")
        self.last_ts = g(
            "weather_last_scrape_timestamp_seconds", "Unix time of last fetch"
        )
        self.temperature = g("weather_temperature_celsius", "Outside air temperature")
        self.humidity = g("weather_humidity_percent", "Outside relative humidity")
        self.wind = g("weather_wind_speed_kmh", "Wind speed (10-min mean)")
        self.gust = g("weather_wind_gust_kmh", "Wind gust (10-min max)")
        self.precip = g("weather_precipitation_mm", "Precipitation (last 10 min)")
        self.cloud = g("weather_cloud_cover_percent", "Cloud cover")
        self.pressure = g("weather_pressure_hpa", "Mean sea-level pressure")
        self.solar = g(
            "weather_solar_kwh_m2", "Global solar radiation (last 10 min sum)"
        )
        self.visibility = g("weather_visibility_meters", "Visibility")
        self.condition = g(
            "weather_condition_info", "Current condition", ("condition", "icon")
        )

    def update(
        self, r: Optional[WeatherReading], *, configured: bool, ok: bool
    ) -> None:
        self.configured.set(1 if configured else 0)
        self.up.set(1 if ok else 0)
        self.last_ts.set(time.time())
        self.condition.clear()
        if r is None or not ok:
            return
        for value, metric in (
            (r.temperature_c, self.temperature),
            (r.humidity_pct, self.humidity),
            (r.wind_speed_kmh, self.wind),
            (r.wind_gust_kmh, self.gust),
            (r.precipitation_mm, self.precip),
            (r.cloud_cover_pct, self.cloud),
            (r.pressure_hpa, self.pressure),
            (r.solar_kwh_m2, self.solar),
            (r.visibility_m, self.visibility),
        ):
            if value is not None:
                metric.set(value)
        if r.condition:
            self.condition.labels(r.condition, r.icon or "").set(1)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def collect_sync(cfg: WeatherConfig, exp: WeatherExporter) -> None:
    if not cfg.configured:
        exp.update(None, configured=False, ok=False)
        return
    try:
        resp = requests.get(
            API,
            params=cfg.params,
            timeout=HTTP_TIMEOUT_S,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        weather = resp.json().get("weather") or {}
        if not weather:
            raise ValueError("no 'weather' object in Bright Sky response")
        r = parse_current(weather)
        exp.update(r, configured=True, ok=True)
        logger.info(
            "weather ok: {}°C, {}% RH, {}",
            r.temperature_c,
            r.humidity_pct,
            r.condition or "?",
        )
    except Exception as exc:  # noqa: BLE001
        exp.update(None, configured=True, ok=False)
        logger.warning("weather fetch failed: {}", exc)


async def collect_once(cfg: WeatherConfig, exp: WeatherExporter) -> None:
    await asyncio.to_thread(collect_sync, cfg, exp)
