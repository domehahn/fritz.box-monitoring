"""Serve bufferbloat metrics on :9132 and run a test on a long interval."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import BufferbloatConfig, BufferbloatExporter, collect_once

PORT = 9132


async def _run() -> None:
    cfg = BufferbloatConfig.from_env()
    exp = BufferbloatExporter()
    await serve(exp, PORT)
    logger.info(
        "bufferbloat interval {}s, target {}:{}",
        cfg.interval_seconds, cfg.target_host, cfg.target_port,
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
