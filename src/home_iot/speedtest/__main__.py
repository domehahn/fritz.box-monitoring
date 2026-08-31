"""Serve speedtest metrics on :9125 and run a test on a long interval."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import SpeedtestConfig, SpeedtestExporter, collect_once

PORT = 9125


async def _run() -> None:
    cfg = SpeedtestConfig.from_env()
    exp = SpeedtestExporter()
    await serve(exp, PORT)
    logger.info("speedtest interval {}s, ~{} MB/run", cfg.interval_seconds, cfg.max_mb)
    await collect_once(cfg, exp)
    await run_loop(cfg.interval_seconds, lambda: collect_once(cfg, exp))


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
