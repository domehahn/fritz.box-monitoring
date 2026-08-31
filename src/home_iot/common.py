"""Shared plumbing for the smart-home exporters.

Every sub-exporter follows the same shape as ``fritz_monitoring.iperf``:

* a frozen ``*Config`` dataclass with a ``from_env()`` constructor,
* an ``*Exporter`` object that owns a ``CollectorRegistry`` and a ``render()``,
* a ``collect_once(cfg, exp)`` that is safe to call on a loop and never raises,
* an aiohttp app serving ``/metrics`` and ``/healthz``.

This module provides the last two pieces so each exporter file only has to
describe *its* metrics and *its* hub call.
"""
from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable, Protocol

from aiohttp import web
from loguru import logger

# Fixed lower bound so a typo in an interval env var cannot hammer a hub.
INTERVAL_FLOOR_S = 15.0


class SupportsRender(Protocol):
    def render(self) -> bytes:
        ...


def env_float(name: str, default: float, *, floor: float = 0.0) -> float:
    try:
        return max(floor, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return max(floor, default)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env_str(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def read_secret(value: str) -> str:
    """Return ``value`` unless it points at an existing file, then its contents.

    Lets any ``*_TOKEN`` / ``*_KEY`` env var carry either the literal secret or a
    path to a Docker secret / mounted file, matching the FRITZ password handling.
    """
    v = (value or "").strip()
    if v and os.path.isfile(v):
        try:
            with open(v, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as exc:  # pragma: no cover - defensive
            logger.warning("could not read secret file {}: {}", v, exc)
            return ""
    return v


def build_app(exp: SupportsRender) -> web.Application:
    app = web.Application()

    async def metrics(_req: web.Request) -> web.Response:
        return web.Response(body=exp.render(), content_type="text/plain")

    async def healthz(_req: web.Request) -> web.Response:
        return web.Response(text="OK")

    app.add_routes([web.get("/metrics", metrics), web.get("/healthz", healthz)])
    return app


async def serve(exp: SupportsRender, port: int) -> None:
    runner = web.AppRunner(build_app(exp))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info("metrics on :{}", port)


async def run_loop(
    interval_s: float,
    tick: Callable[[], Awaitable[None]],
) -> None:
    """Call ``tick`` every ``interval_s`` seconds forever, swallowing errors."""
    while True:
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the loop
            logger.exception("collection tick failed: {}", exc)
        await asyncio.sleep(interval_s)
