"""Serve annotator metrics on :9134 and watch health signals for outages."""
from __future__ import annotations

import asyncio

from loguru import logger

from ..common import run_loop, serve
from .exporter import AnnotatorConfig, AnnotatorMetrics, collect_once

PORT = 9134


class _M:
    """Adapt AnnotatorMetrics to the common serve() render() protocol."""

    def __init__(self, m: AnnotatorMetrics) -> None:
        self._m = m

    def render(self) -> bytes:
        return self._m.render()


async def _run() -> None:
    cfg = AnnotatorConfig.from_env()
    m = AnnotatorMetrics()
    await serve(_M(m), PORT)
    logger.info(
        "annotator: signals={} grafana={} every {}s",
        ",".join(cfg.signals), cfg.grafana_url, cfg.interval_seconds,
    )
    if not cfg.grafana_password:
        logger.warning("GRAFANA_PASSWORD not set — annotations will 401")
    await collect_once(cfg, m)
    await run_loop(cfg.interval_seconds, lambda: collect_once(cfg, m))


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
