"""Serve FRITZ!DECT metrics on :9123 and poll the box on a fixed interval."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import FritzDectConfig, FritzDectExporter, collect_once

PORT = 9123


async def _run() -> None:
    cfg = FritzDectConfig.from_env()
    exp = FritzDectExporter()
    await serve(exp, PORT)
    if not cfg.configured:
        logger.warning(
            "FRITZ credentials not set — serving fritzdect_configured=0 only."
        )
    else:
        logger.info(
            "polling FRITZ!DECT on {} every {}s", cfg.host, cfg.interval_seconds
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
