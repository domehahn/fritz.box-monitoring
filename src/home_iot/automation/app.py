"""Home-automation service — reads Prometheus, decides, and (only if
``AUTOMATION_DRY_RUN=false``) nudges the Bosch SHC / Hue bridge.

**Dry-run is the default.** In dry-run nothing touches a device: decisions are
logged, counted (``automation_action_planned_total``) and, if ``NTFY_TOPIC`` is
set, pushed as a "would do X" note.

HTTP: ``/metrics``, ``/healthz``, ``/state`` (last decisions), ``POST /run``.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests
from aiohttp import web
from loguru import logger
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

from ..common import env_bool, env_float, env_str, read_secret
from . import executors
from .rules import Decision, Snapshot, Tunables, evaluate

PORT = 9131
INTERVAL_FLOOR_S = 60.0

_SNAPSHOT_QUERIES = {
    "occupied_now": "home:occupied:bool",
    "valve_max": "max(bosch_device_valve_percent)",
    "setpoint_min": "min(bosch_device_setpoint_celsius)",
    "setpoint_max": "max(bosch_device_setpoint_celsius)",
    "lights_on": "sum(hue_light_on)",
}


@dataclass
class Config:
    prom: str
    dry_run: bool
    interval_s: float
    tun: Tunables
    bosch: Tuple[str, str, str]  # (host, cert, key)
    hue: Tuple[str, str]  # (host, app_key)
    ntfy: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            prom=env_str("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/"),
            dry_run=env_bool("AUTOMATION_DRY_RUN", True),
            interval_s=env_float(
                "AUTOMATION_INTERVAL_SECONDS", 300.0, floor=INTERVAL_FLOOR_S
            ),
            tun=Tunables(
                away_minutes=int(env_float("AUTOMATION_AWAY_MINUTES", 45.0)),
                setback_c=env_float("AUTOMATION_SETBACK_C", 17.0),
                comfort_c=env_float("AUTOMATION_COMFORT_C", 21.0),
                lights_away_minutes=int(
                    env_float("AUTOMATION_LIGHTS_AWAY_MINUTES", 20.0)
                ),
            ),
            bosch=(
                env_str("BOSCH_SHC_HOST"),
                env_str("BOSCH_SHC_CERT_FILE"),
                env_str("BOSCH_SHC_KEY_FILE"),
            ),
            hue=(env_str("HUE_BRIDGE_HOST"), read_secret(env_str("HUE_APP_KEY"))),
            ntfy={
                "url": env_str("NTFY_URL", "https://ntfy.sh").rstrip("/"),
                "topic": read_secret(env_str("NTFY_TOPIC")),
                "token": read_secret(env_str("NTFY_TOKEN")),
            },
        )


class Metrics:
    def __init__(self) -> None:
        self.reg = CollectorRegistry()
        self.up = Gauge("automation_up", "1 if the last eval completed", registry=self.reg)
        self.dry = Gauge(
            "automation_dry_run", "1 if in dry-run (no device writes)", registry=self.reg
        )
        self.last_ts = Gauge(
            "automation_last_eval_timestamp_seconds",
            "Unix time of the last evaluation",
            registry=self.reg,
        )
        self.matched = Gauge(
            "automation_rule_matched",
            "1 if the rule matched on the last eval",
            ["rule"],
            registry=self.reg,
        )
        self.planned = Counter(
            "automation_action_planned_total",
            "Actions a rule decided on (dry-run or live)",
            ["rule", "action"],
            registry=self.reg,
        )
        self.executed = Counter(
            "automation_action_executed_total",
            "Actions actually sent to a device (live only)",
            ["rule", "action"],
            registry=self.reg,
        )
        self.failed = Counter(
            "automation_action_failures_total",
            "Device writes that failed",
            ["rule", "action"],
            registry=self.reg,
        )

    def render(self) -> bytes:
        return generate_latest(self.reg)


def _scalar(base: str, expr: str) -> Optional[float]:
    try:
        r = requests.get(
            f"{base}/api/v1/query", params={"query": expr}, timeout=15
        )
        r.raise_for_status()
        res = r.json()["data"]["result"]
        return float(res[0]["value"][1]) if res else None
    except Exception:  # noqa: BLE001
        return None


def read_snapshot(cfg: Config) -> Snapshot:
    q = {k: _scalar(cfg.prom, v) for k, v in _SNAPSHOT_QUERIES.items()}
    win = _scalar(
        cfg.prom,
        f"max_over_time(home:occupied:bool[{cfg.tun.away_minutes}m])",
    )
    return Snapshot(
        occupied_now=q["occupied_now"],
        occupied_window_max=win,
        valve_max=q["valve_max"],
        setpoint_min=q["setpoint_min"],
        setpoint_max=q["setpoint_max"],
        lights_on=q["lights_on"],
    )


def _notify(cfg: Config, title: str, body: str) -> None:
    if not cfg.ntfy["topic"]:
        return
    headers = {
        "Title": " ".join(title.encode("ascii", "ignore").decode().split()) or "automation",
        "Priority": "2",
        "Tags": "robot",
    }
    if cfg.ntfy["token"]:
        headers["Authorization"] = f"Bearer {cfg.ntfy['token']}"
    try:
        requests.post(
            f"{cfg.ntfy['url']}/{cfg.ntfy['topic']}",
            data=body.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("automation ntfy failed: {}", exc)


def _execute(cfg: Config, d: Decision) -> tuple:
    if d.action.kind == "bosch_setpoints":
        return executors.apply_bosch_setpoints(*cfg.bosch, d.action.params["celsius"])
    if d.action.kind == "hue_all_off":
        return executors.apply_hue_all_off(*cfg.hue)
    return False, f"unknown action {d.action.kind}"


@dataclass
class State:
    last_fired: Dict[str, float] = field(default_factory=dict)
    last_decisions: List[dict] = field(default_factory=list)
    last_eval: float = 0.0


def tick(cfg: Config, m: Metrics, st: State) -> None:
    now = time.time()
    snap = read_snapshot(cfg)
    decisions = evaluate(snap, st.last_fired, now, cfg.tun)
    fired = {d.rule for d in decisions}
    from .rules import RULES

    for r in RULES:
        m.matched.labels(rule=r.name).set(1 if r.name in fired else 0)

    log: List[dict] = []
    for d in decisions:
        m.planned.labels(rule=d.rule, action=d.action.kind).inc()
        st.last_fired[d.rule] = now
        entry = {
            "ts": now,
            "rule": d.rule,
            "reason": d.reason,
            "action": d.action.human,
            "mode": "dry-run" if cfg.dry_run else "live",
        }
        if cfg.dry_run:
            logger.info("[dry-run] {} -> would {} ({})", d.rule, d.action.human, d.reason)
            _notify(cfg, f"🤖 would {d.action.human}", f"{d.rule}: {d.reason}")
        else:
            ok, detail = _execute(cfg, d)
            entry["result"] = ("ok: " if ok else "FAILED: ") + detail
            (m.executed if ok else m.failed).labels(
                rule=d.rule, action=d.action.kind
            ).inc()
            logger.info("[live] {} -> {} ({})", d.rule, entry["result"], d.reason)
            _notify(
                cfg,
                f"🤖 {'done' if ok else 'FAILED'}: {d.action.human}",
                f"{d.rule}: {d.reason}\n{detail}",
            )
        log.append(entry)

    st.last_decisions = (log + st.last_decisions)[:20]
    st.last_eval = now
    m.last_ts.set(now)
    m.up.set(1)
    m.dry.set(1 if cfg.dry_run else 0)


def build_app(cfg: Config, m: Metrics, st: State) -> web.Application:
    async def metrics(_r: web.Request) -> web.Response:
        return web.Response(body=m.render(), content_type="text/plain")

    async def healthz(_r: web.Request) -> web.Response:
        return web.Response(text="OK")

    async def state(_r: web.Request) -> web.Response:
        return web.Response(
            text=json.dumps(
                {
                    "dry_run": cfg.dry_run,
                    "last_eval": st.last_eval,
                    "decisions": st.last_decisions,
                },
                indent=2,
            ),
            content_type="application/json",
        )

    async def run(_r: web.Request) -> web.Response:
        await asyncio.to_thread(tick, cfg, m, st)
        return web.json_response({"ok": True, "decisions": st.last_decisions[:5]})

    app = web.Application()
    app.add_routes(
        [
            web.get("/metrics", metrics),
            web.get("/healthz", healthz),
            web.get("/state", state),
            web.get("/run", run),
            web.post("/run", run),
        ]
    )
    return app


async def _main() -> None:
    cfg = Config.from_env()
    m = Metrics()
    m.dry.set(1 if cfg.dry_run else 0)
    st = State()
    runner = web.AppRunner(build_app(cfg, m, st))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info(
        "automation on :{} — {} mode, every {:.0f}s",
        PORT,
        "DRY-RUN" if cfg.dry_run else "LIVE",
        cfg.interval_s,
    )
    while True:
        try:
            await asyncio.to_thread(tick, cfg, m, st)
        except Exception as exc:  # noqa: BLE001
            m.up.set(0)
            logger.exception("automation tick failed: {}", exc)
        await asyncio.sleep(cfg.interval_s)


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
