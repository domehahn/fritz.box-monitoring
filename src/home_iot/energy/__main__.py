"""Serve energy price / meter metrics on :9128."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import EnergyConfig, EnergyExporter, collect_once

PORT = 9128


async def _run() -> None:
    cfg = EnergyConfig.from_env()
    exp = EnergyExporter()
    await serve(exp, PORT)
    src = "tibber" if cfg.tibber_token else cfg.market
    logger.info(
        "energy: price via {}{}",
        src,
        f", meter via shelly {cfg.shelly_host}" if cfg.shelly_host else "",
    )
    await collect_once(cfg, exp)
    await run_loop(cfg.interval_seconds, lambda: collect_once(cfg, exp))


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
