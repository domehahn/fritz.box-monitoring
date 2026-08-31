"""Serve weather metrics on :9124 and poll Bright Sky on a fixed interval."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import WeatherConfig, WeatherExporter, collect_once

PORT = 9124


async def _run() -> None:
    cfg = WeatherConfig.from_env()
    exp = WeatherExporter()
    await serve(exp, PORT)
    if not cfg.configured:
        logger.warning(
            "WEATHER_LAT/WEATHER_LON (or WEATHER_STATION) not set — serving "
            "weather_configured=0 only."
        )
    else:
        logger.info("polling Bright Sky every {}s", cfg.interval_seconds)
    await collect_once(cfg, exp)
    await run_loop(cfg.interval_seconds, lambda: collect_once(cfg, exp))


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
