"""Serve netwatch metrics on :9133 and poll Prometheus for new devices."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import NetwatchConfig, NetwatchExporter, collect_once

PORT = 9133


async def _run() -> None:
    cfg = NetwatchConfig.from_env()
    exp = NetwatchExporter()
    await serve(exp, PORT)
    logger.info(
        "netwatch: every {}s, new-window {} days, state {}",
        cfg.interval_seconds, cfg.new_days, cfg.state_path,
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
