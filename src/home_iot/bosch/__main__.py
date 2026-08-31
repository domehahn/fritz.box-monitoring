"""Serve Bosch SHC metrics on :9121 and poll the controller on a fixed interval."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import BoschConfig, BoschExporter, collect_once

PORT = 9121


async def _run() -> None:
    cfg = BoschConfig.from_env()
    exp = BoschExporter()
    await serve(exp, PORT)
    if not cfg.configured:
        logger.warning(
            "BOSCH_SHC_HOST / client cert not set — serving bosch_shc_configured=0 "
            "only. See docs/smart-home-exporters.md to pair the controller."
        )
    else:
        logger.info("polling Bosch SHC {} every {}s", cfg.host, cfg.interval_seconds)
    await collect_once(cfg, exp)
    await run_loop(cfg.interval_seconds, lambda: collect_once(cfg, exp))


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
