"""Entry point: serve /metrics on :9119 and run iperf3 on a long interval."""
import asyncio

from aiohttp import web
from loguru import logger

from .probe import IperfConfig, IperfExporter, _loop


def build_app(exp: IperfExporter) -> web.Application:
    app = web.Application()

    async def metrics(_req: web.Request) -> web.Response:
        return web.Response(body=exp.render(), content_type="text/plain")

    async def healthz(_req: web.Request) -> web.Response:
        return web.Response(text="OK")

    app.add_routes([web.get("/metrics", metrics), web.get("/healthz", healthz)])
    return app


async def _run() -> None:
    cfg = IperfConfig.from_env()
    exp = IperfExporter()
    if not cfg.target:
        logger.warning(
            "IPERF_TARGET not set — serving iperf_enabled=0 only. Point it at a "
            "wired LAN host running 'iperf3 -s' to enable."
        )
    runner = web.AppRunner(build_app(exp))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 9119).start()
    logger.info("iperf-probe metrics on :9119 (interval {}s)", cfg.interval_seconds)
    await _loop(cfg, exp)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
