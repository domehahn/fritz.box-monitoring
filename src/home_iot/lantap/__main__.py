"""Serve per-device byte counters on :9129; capture runs in a background thread."""
from __future__ import annotations

import asyncio
import threading

from loguru import logger

from ..common import serve
from .exporter import LanTapConfig, LanTapExporter, capture_loop

PORT = 9129


async def _run() -> None:
    cfg = LanTapConfig.from_env()
    exp = LanTapExporter()
    await serve(exp, PORT)
    if not cfg.configured:
        logger.warning("FRITZ credentials not set — lantap idle (lantap_configured=0)")
        exp.configured.set(0)
    else:
        logger.warning(
            "lantap taps {} on {} — this loads the FRITZ!Box CPU; keep sessions "
            "short or set LANTAP_MAX_MINUTES.",
            cfg.iface,
            cfg.host,
        )
        stop = threading.Event()
        threading.Thread(
            target=capture_loop, args=(cfg, exp, stop), daemon=True, name="lantap"
        ).start()
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
