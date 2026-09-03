"""Serve Sungrow PV metrics on :9135, polling the WiNet-S local WebSocket."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import SungrowConfig, SungrowExporter, WiNetClient, collect_once

PORT = 9135


async def _run() -> None:
    cfg = SungrowConfig.from_env()
    exp = SungrowExporter()
    await serve(exp, PORT)
    if not cfg.configured:
        logger.warning("SUNGROW_HOST not set — exporter idle on :{}", PORT)
        while True:
            await asyncio.sleep(3600)
    client = WiNetClient(cfg)
    logger.info("sungrow: {} every {}s", client.url, cfg.interval_seconds)
    await collect_once(client, exp)
    await run_loop(cfg.interval_seconds, lambda: collect_once(client, exp))


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
