"""Serve Blink metrics on :9122 and refresh from the Blink cloud on an interval."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import BlinkConfig, BlinkExporter, collect_once

PORT = 9122


async def _run() -> None:
    cfg = BlinkConfig.from_env()
    exp = BlinkExporter()
    await serve(exp, PORT)
    if not cfg.configured:
        logger.warning(
            "BLINK_USERNAME / BLINK_PASSWORD not set — serving blink_configured=0 "
            "only. See docs/smart-home-exporters.md."
        )
    else:
        logger.info("refreshing Blink cloud every {}s", cfg.interval_seconds)
    await collect_once(cfg, exp)
    await run_loop(cfg.interval_seconds, lambda: collect_once(cfg, exp))


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
