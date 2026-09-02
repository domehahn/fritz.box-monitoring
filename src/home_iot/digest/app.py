"""Weekly digest service: on a schedule (default Mon 09:00), query Prometheus,
build a summary, push it to ntfy. HTTP: /run (fire now), /healthz, /metrics."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import List, Optional, Tuple

import requests
from aiohttp import web
from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float, env_str, read_secret
from .report import build_report

PORT = 9130


def _cfg() -> dict:
    return {
        "prom": env_str("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/"),
        "ntfy_url": env_str("NTFY_URL", "https://ntfy.sh").rstrip("/"),
        "ntfy_topic": read_secret(env_str("NTFY_TOPIC")),
        "ntfy_token": read_secret(env_str("NTFY_TOKEN")),
        "day": int(env_float("DIGEST_DAY", 0.0)),  # 0 = Monday
        "hour": int(env_float("DIGEST_HOUR", 9.0)),
        "window": env_str("DIGEST_WINDOW", "7d"),
    }


def _prom_scalar(base: str):
    def q(expr: str) -> Optional[float]:
        try:
            r = requests.get(f"{base}/api/v1/query", params={"query": expr}, timeout=15)
            r.raise_for_status()
            res = r.json()["data"]["result"]
            return float(res[0]["value"][1]) if res else None
        except Exception:  # noqa: BLE001
            return None

    return q


def _prom_vector(base: str):
    def qv(expr: str) -> List[Tuple[dict, float]]:
        try:
            r = requests.get(f"{base}/api/v1/query", params={"query": expr}, timeout=15)
            r.raise_for_status()
            return [
                (x["metric"], float(x["value"][1])) for x in r.json()["data"]["result"]
            ]
        except Exception:  # noqa: BLE001
            return []

    return qv


def _publish(cfg: dict, title: str, body: str) -> None:
    # HTTP headers are latin-1 and must not have leading/interior control chars
    safe_title = " ".join(title.encode("ascii", "ignore").decode().split()) or "Weekly digest"
    headers = {
        "Title": safe_title,
        "Priority": "2",
        "Tags": "bar_chart",
        "Markdown": "yes",
    }
    if cfg["ntfy_token"]:
        headers["Authorization"] = f"Bearer {cfg['ntfy_token']}"
    resp = requests.post(
        f"{cfg['ntfy_url']}/{cfg['ntfy_topic']}",
        data=body.encode("utf-8"),
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()


class _Metrics:
    def __init__(self) -> None:
        self.reg = CollectorRegistry()
        self.last_ts = Gauge(
            "digest_last_run_timestamp_seconds",
            "Unix time of the last digest run",
            registry=self.reg,
        )
        self.ok = Gauge(
            "digest_last_run_success", "1 if the last run pushed ok", registry=self.reg
        )
        self.next_ts = Gauge(
            "digest_next_run_timestamp_seconds",
            "Unix time of the next scheduled run",
            registry=self.reg,
        )

    def render(self) -> bytes:
        return generate_latest(self.reg)


def run_once(cfg: dict, m: _Metrics) -> bool:
    title, body = build_report(
        _prom_scalar(cfg["prom"]), _prom_vector(cfg["prom"]), cfg["window"]
    )
    m.last_ts.set(time.time())
    if not cfg["ntfy_topic"]:
        logger.warning("NTFY_TOPIC not set — digest built but not sent:\n{}", body)
        m.ok.set(0)
        return False
    try:
        _publish(cfg, title, body)
        logger.info("weekly digest pushed to ntfy")
        m.ok.set(1)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("digest push failed: {}", exc)
        m.ok.set(0)
        return False


def seconds_until(day: int, hour: int, now: Optional[dt.datetime] = None) -> float:
    now = now or dt.datetime.now()
    days_ahead = (day - now.weekday()) % 7
    target = (now + dt.timedelta(days=days_ahead)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    if target <= now:
        target += dt.timedelta(days=7)
    return (target - now).total_seconds()


async def _scheduler(cfg: dict, m: _Metrics) -> None:
    while True:
        wait = seconds_until(cfg["day"], cfg["hour"])
        m.next_ts.set(time.time() + wait)
        logger.info("next digest in {:.1f} h", wait / 3600)
        await asyncio.sleep(wait)
        await asyncio.to_thread(run_once, cfg, m)
        await asyncio.sleep(60)  # avoid a double-fire in the same minute


def build_app(cfg: dict, m: _Metrics) -> web.Application:
    async def run(_req: web.Request) -> web.Response:
        ok = await asyncio.to_thread(run_once, cfg, m)
        return web.json_response({"sent": ok})

    async def metrics(_req: web.Request) -> web.Response:
        return web.Response(body=m.render(), content_type="text/plain")

    async def healthz(_req: web.Request) -> web.Response:
        return web.Response(text="OK")

    app = web.Application()
    app.add_routes(
        [
            web.get("/run", run),
            web.post("/run", run),
            web.get("/metrics", metrics),
            web.get("/healthz", healthz),
        ]
    )
    return app


async def _main() -> None:
    cfg = _cfg()
    m = _Metrics()
    runner = web.AppRunner(build_app(cfg, m))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info(
        "digest on :{} — schedule day={} hour={}", PORT, cfg["day"], cfg["hour"]
    )
    await _scheduler(cfg, m)


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
