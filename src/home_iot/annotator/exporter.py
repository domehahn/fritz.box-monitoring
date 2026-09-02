"""Outage annotator: watch a few health signals and drop a Grafana annotation
that spans each outage, so every dashboard shows *"internet was down here"*.

* on a 1 -> 0 transition: ``POST /api/annotations`` (region start), remember the id
* on a 0 -> 1 transition: ``PATCH /api/annotations/:id`` with ``timeEnd``

The open-annotation ids are persisted (``/data/annotator.json``) so a restart
mid-outage can still close them. :func:`transitions` is pure.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from loguru import logger
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

from ..common import env_float, env_str, read_secret

INTERVAL_FLOOR_S = 15.0

#: signal name -> (PromQL, human label)
SIGNALS: Dict[str, Tuple[str, str]] = {
    "internet": ("home:health:internet_reachability", "Internet unreachable"),
    "dns": ("home:health:dns", "DNS resolution failing"),
    "health": ("home:network_health:score >= bool 0.6", "Network health critical"),
}


@dataclass(frozen=True)
class AnnotatorConfig:
    prom_url: str = "http://prometheus:9090"
    grafana_url: str = "http://grafana:3000"
    grafana_user: str = "admin"
    grafana_password: str = ""
    signals: Tuple[str, ...] = ("internet", "dns")
    state_path: str = "/data/annotator.json"
    interval_seconds: float = 30.0
    min_outage_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "AnnotatorConfig":
        want = env_str("ANNOTATOR_SIGNALS", "internet,dns").replace(" ", "")
        sig = tuple(s for s in want.split(",") if s in SIGNALS) or ("internet",)
        return cls(
            prom_url=env_str("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/"),
            grafana_url=env_str("GRAFANA_URL", "http://grafana:3000").rstrip("/"),
            grafana_user=env_str("GRAFANA_USER", "admin"),
            grafana_password=read_secret(env_str("GRAFANA_PASSWORD")),
            signals=sig,
            state_path=env_str("ANNOTATOR_STATE_PATH", "/data/annotator.json"),
            interval_seconds=env_float(
                "ANNOTATOR_INTERVAL_SECONDS", 30.0, floor=INTERVAL_FLOOR_S
            ),
            min_outage_seconds=env_float("ANNOTATOR_MIN_OUTAGE_SECONDS", 60.0),
        )


@dataclass
class Event:
    signal: str
    kind: str  # "open" | "close"
    ann_id: Optional[int] = None  # for "close"


@dataclass
class OpenAnn:
    ann_id: int
    started: float


def transitions(
    readings: Dict[str, Optional[float]],
    open_anns: Dict[str, OpenAnn],
) -> List[Event]:
    """Pure: given current 0..1 readings and the currently-open annotations,
    return the open/close events to apply. A ``None`` reading (query failed)
    is ignored so a scrape gap doesn't fake an outage.
    """
    out: List[Event] = []
    for sig, val in readings.items():
        if val is None:
            continue
        down = val < 0.5
        if down and sig not in open_anns:
            out.append(Event(sig, "open"))
        elif not down and sig in open_anns:
            out.append(Event(sig, "close", open_anns[sig].ann_id))
    return out


class AnnotatorMetrics:
    def __init__(self) -> None:
        self.reg = CollectorRegistry()
        self.up = Gauge("annotator_up", "1 if the last cycle completed", registry=self.reg)
        self.outage = Gauge(
            "annotator_outage_active", "1 while an outage annotation is open",
            ["signal"], registry=self.reg,
        )
        self.created = Counter(
            "annotator_annotations_created_total", "Outage annotations opened",
            ["signal"], registry=self.reg,
        )
        self.closed = Counter(
            "annotator_annotations_closed_total", "Outage annotations closed",
            ["signal"], registry=self.reg,
        )
        self.errors = Counter(
            "annotator_grafana_errors_total", "Grafana API call failures",
            registry=self.reg,
        )
        self.last_ts = Gauge(
            "annotator_last_cycle_timestamp_seconds", "Unix time of the last cycle",
            registry=self.reg,
        )

    def render(self) -> bytes:
        return generate_latest(self.reg)


def _load(path: str) -> Dict[str, OpenAnn]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return {k: OpenAnn(int(v["ann_id"]), float(v["started"])) for k, v in raw.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _save(path: str, open_anns: Dict[str, OpenAnn]) -> None:
    tmp = f"{path}.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {k: {"ann_id": v.ann_id, "started": v.started}
                 for k, v in open_anns.items()},
                fh,
            )
        os.replace(tmp, path)
    except OSError as exc:  # pragma: no cover
        logger.warning("could not persist annotator state: {}", exc)


def _prom(cfg: AnnotatorConfig, expr: str) -> Optional[float]:
    try:
        r = requests.get(
            f"{cfg.prom_url}/api/v1/query", params={"query": expr}, timeout=10
        )
        r.raise_for_status()
        res = r.json()["data"]["result"]
        return float(res[0]["value"][1]) if res else None
    except Exception:  # noqa: BLE001
        return None


def _grafana(cfg: AnnotatorConfig):
    s = requests.Session()
    if cfg.grafana_password:
        s.auth = (cfg.grafana_user, cfg.grafana_password)
    return s


def collect_sync(cfg: AnnotatorConfig, m: AnnotatorMetrics) -> None:
    now = time.time()
    readings = {s: _prom(cfg, SIGNALS[s][0]) for s in cfg.signals}
    open_anns = _load(cfg.state_path)
    events = transitions(readings, open_anns)

    s = _grafana(cfg)
    changed = False
    for ev in events:
        label = SIGNALS[ev.signal][1]
        try:
            if ev.kind == "open":
                resp = s.post(
                    f"{cfg.grafana_url}/api/annotations",
                    json={
                        "time": int(now * 1000),
                        "tags": ["outage", ev.signal],
                        "text": f"⚠️ {label}",
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                open_anns[ev.signal] = OpenAnn(int(resp.json()["id"]), now)
                m.created.labels(ev.signal).inc()
                changed = True
                logger.warning("opened outage annotation for {}", ev.signal)
            else:
                started = open_anns.get(ev.signal)
                dur = now - started.started if started else 0.0
                if started and dur < cfg.min_outage_seconds:
                    # blip: delete rather than leave a 5s scar on every graph
                    s.delete(
                        f"{cfg.grafana_url}/api/annotations/{ev.ann_id}", timeout=10
                    )
                else:
                    r = s.patch(
                        f"{cfg.grafana_url}/api/annotations/{ev.ann_id}",
                        json={
                            "timeEnd": int(now * 1000),
                            "text": f"{label} — {int(dur)}s",
                        },
                        timeout=10,
                    )
                    r.raise_for_status()
                open_anns.pop(ev.signal, None)
                m.closed.labels(ev.signal).inc()
                changed = True
                logger.info("closed outage annotation for {} ({:.0f}s)", ev.signal, dur)
        except Exception as exc:  # noqa: BLE001
            m.errors.inc()
            logger.warning("grafana annotation call failed ({}): {}", ev.kind, exc)

    if changed:
        _save(cfg.state_path, open_anns)
    for sig in cfg.signals:
        m.outage.labels(sig).set(1 if sig in open_anns else 0)
    m.up.set(1)
    m.last_ts.set(now)


async def collect_once(cfg: AnnotatorConfig, m: AnnotatorMetrics) -> None:
    import asyncio

    await asyncio.to_thread(collect_sync, cfg, m)
