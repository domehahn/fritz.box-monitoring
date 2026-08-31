"""Serve per-container metrics on :9126 from the Docker Engine socket."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import DockerStatsConfig, DockerStatsExporter, collect_once

PORT = 9126


async def _run() -> None:
    cfg = DockerStatsConfig.from_env()
    exp = DockerStatsExporter()
    await serve(exp, PORT)
    logger.info(
        "polling Docker socket {} every {}s", cfg.socket_path, cfg.interval_seconds
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
