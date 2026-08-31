"""Serve Hue metrics on :9120 and poll the bridge on a fixed interval."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import HueConfig, HueExporter, collect_once

PORT = 9120


async def _run() -> None:
    cfg = HueConfig.from_env()
    exp = HueExporter()
    await serve(exp, PORT)
    if not cfg.configured:
        logger.warning(
            "HUE_BRIDGE_HOST / HUE_APP_KEY not set — serving hue_configured=0 only. "
            "See docs/smart-home-exporters.md to pair the bridge."
        )
    else:
        logger.info(
            "polling Hue bridge {} every {}s", cfg.bridge_host, cfg.interval_seconds
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
