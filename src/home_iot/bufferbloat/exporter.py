"""Latency-under-load (bufferbloat) -> Prometheus.

Speedtest tells you the pipe is fat; this tells you whether it *chokes* when
full — the thing that actually wrecks video calls and gaming. Every run:

1. sample TCP-connect latency to a stable host while the line is idle,
2. sample it again while a large download from ``speed.cloudflare.com`` runs,
3. and again during a large upload.

Bufferbloat = loaded latency − idle latency. :func:`grade` and
:func:`summarise` are pure.
"""
from __future__ import annotations

import socket
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

import requests
from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float, env_str

INTERVAL_FLOOR_S = 300.0
DOWN_URL = "https://speed.cloudflare.com/__down"
UP_URL = "https://speed.cloudflare.com/__up"
HTTP_TIMEOUT_S = 30.0
# Cloudflare's __down 403s above ~50 MB; request 25 MB chunks and loop.
CHUNK_BYTES = 25 * 1024 * 1024

# increase (loaded − idle) thresholds, seconds -> (letter, ordinal 0=A..4=F)
_GRADES = [
    (0.005, "A", 0.0),
    (0.030, "B", 1.0),
    (0.060, "C", 2.0),
    (0.200, "D", 3.0),
]


@dataclass(frozen=True)
class BufferbloatConfig:
    interval_seconds: float = 900.0
    target_host: str = "1.1.1.1"
    target_port: int = 443
    load_seconds: float = 8.0
    sample_gap_seconds: float = 0.25

    @classmethod
    def from_env(cls) -> "BufferbloatConfig":
        return cls(
            interval_seconds=env_float(
                "BUFFERBLOAT_INTERVAL_SECONDS", 900.0, floor=INTERVAL_FLOOR_S
            ),
            target_host=env_str("BUFFERBLOAT_TARGET_HOST", "1.1.1.1"),
            target_port=int(env_float("BUFFERBLOAT_TARGET_PORT", 443.0)),
            load_seconds=env_float("BUFFERBLOAT_LOAD_SECONDS", 8.0, floor=3.0),
            sample_gap_seconds=env_float(
                "BUFFERBLOAT_SAMPLE_GAP_SECONDS", 0.25, floor=0.05
            ),
        )


@dataclass
class BufferbloatResult:
    success: bool = False
    idle: Dict[str, float] = field(default_factory=dict)
    loaded_down: Dict[str, float] = field(default_factory=dict)
    loaded_up: Dict[str, float] = field(default_factory=dict)
    down_mbps: float = 0.0
    up_mbps: float = 0.0
    error: str = ""

    @property
    def increase_down(self) -> float:
        return max(0.0, self.loaded_down.get("p50", 0.0) - self.idle.get("p50", 0.0))

    @property
    def increase_up(self) -> float:
        return max(0.0, self.loaded_up.get("p50", 0.0) - self.idle.get("p50", 0.0))


def summarise(samples: List[float]) -> Dict[str, float]:
    """min / p50 / p95 / count of the positive connect times."""
    clean = sorted(x for x in samples if x > 0)
    if not clean:
        return {"min": 0.0, "p50": 0.0, "p95": 0.0, "count": 0.0}

    def pct(p: float) -> float:
        idx = min(len(clean) - 1, int(round(p * (len(clean) - 1))))
        return clean[idx]

    return {
        "min": clean[0],
        "p50": statistics.median(clean),
        "p95": pct(0.95),
        "count": float(len(clean)),
    }


def grade(increase_s: float) -> tuple[str, float]:
    for thresh, letter, ordinal in _GRADES:
        if increase_s < thresh:
            return letter, ordinal
    return "F", 4.0


def _connect_once(host: str, port: int, timeout: float = 3.0) -> float:
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return time.perf_counter() - t0
    except OSError:
        return 0.0


def _sample_latency(cfg: BufferbloatConfig, duration: float) -> List[float]:
    out: List[float] = []
    end = time.perf_counter() + duration
    while time.perf_counter() < end:
        out.append(_connect_once(cfg.target_host, cfg.target_port))
        time.sleep(cfg.sample_gap_seconds)
    return out


class _Load:
    """Run a Cloudflare transfer in a background thread; report Mbit/s."""

    def __init__(self, kind: str, nbytes: int) -> None:
        self.kind = kind
        self.nbytes = nbytes
        self.mbps = 0.0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "_Load":
        self._t.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._t.join(timeout=HTTP_TIMEOUT_S)

    def _run(self) -> None:
        t0 = time.perf_counter()
        moved = 0
        try:
            if self.kind == "down":
                while not self._stop.is_set():
                    req = min(CHUNK_BYTES, self.nbytes - moved)
                    if req <= 0:
                        break
                    with requests.get(
                        DOWN_URL,
                        params={"bytes": req},
                        stream=True,
                        timeout=HTTP_TIMEOUT_S,
                    ) as r:
                        r.raise_for_status()
                        for chunk in r.iter_content(chunk_size=65536):
                            moved += len(chunk)
                            if self._stop.is_set():
                                break
            else:
                def gen() -> Iterator[bytes]:
                    nonlocal moved
                    block = b"\x00" * 65536
                    while moved < self.nbytes and not self._stop.is_set():
                        moved += len(block)
                        yield block

                requests.post(
                    UP_URL,
                    data=gen(),
                    timeout=HTTP_TIMEOUT_S,
                    headers={"Content-Type": "application/octet-stream"},
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("{} load ended: {}", self.kind, exc)
        elapsed = time.perf_counter() - t0
        if elapsed > 0:
            self.mbps = moved * 8 / elapsed / 1e6


def run_bufferbloat(cfg: BufferbloatConfig) -> BufferbloatResult:
    res = BufferbloatResult()
    try:
        res.idle = summarise(_sample_latency(cfg, min(4.0, cfg.load_seconds)))

        big = 400 * 1024 * 1024  # cap; the transfer is stopped after load_seconds
        with _Load("down", big) as load:
            res.loaded_down = summarise(_sample_latency(cfg, cfg.load_seconds))
        res.down_mbps = load.mbps

        with _Load("up", big // 2) as load:
            res.loaded_up = summarise(_sample_latency(cfg, cfg.load_seconds))
        res.up_mbps = load.mbps

        res.success = res.idle["count"] > 0 and res.loaded_down["count"] > 0
        return res
    except Exception as exc:  # noqa: BLE001
        res.error = str(exc)
        return res


class BufferbloatExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.registry)

        self.up = g("bufferbloat_up", "1 if the last run produced a result")
        self.last_ts = g(
            "bufferbloat_last_run_timestamp_seconds", "Unix time of last run"
        )
        self.idle = g(
            "bufferbloat_idle_latency_seconds", "Idle TCP-connect latency", ("quantile",)
        )
        self.down = g(
            "bufferbloat_loaded_down_latency_seconds",
            "TCP-connect latency during a download",
            ("quantile",),
        )
        self.upl = g(
            "bufferbloat_loaded_up_latency_seconds",
            "TCP-connect latency during an upload",
            ("quantile",),
        )
        self.inc_down = g(
            "bufferbloat_increase_down_seconds", "p50 latency rise under download load"
        )
        self.inc_up = g(
            "bufferbloat_increase_up_seconds", "p50 latency rise under upload load"
        )
        self.grade = g(
            "bufferbloat_grade", "0=A (none) .. 4=F (severe), worst of down/up"
        )
        self.dl = g("bufferbloat_download_mbps", "Download rate during the load test")
        self.ul = g("bufferbloat_upload_mbps", "Upload rate during the load test")

    def update(self, r: BufferbloatResult) -> None:
        self.last_ts.set(time.time())
        self.up.set(1 if r.success else 0)
        if not r.success:
            return
        for q in ("min", "p50", "p95"):
            self.idle.labels(q).set(r.idle.get(q, 0.0))
            self.down.labels(q).set(r.loaded_down.get(q, 0.0))
            self.upl.labels(q).set(r.loaded_up.get(q, 0.0))
        self.inc_down.set(r.increase_down)
        self.inc_up.set(r.increase_up)
        self.grade.set(max(grade(r.increase_down)[1], grade(r.increase_up)[1]))
        self.dl.set(r.down_mbps)
        self.ul.set(r.up_mbps)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def collect_sync(cfg: BufferbloatConfig, exp: BufferbloatExporter) -> None:
    logger.info("bufferbloat: probing {}:{} under load ...", cfg.target_host, cfg.target_port)
    r = run_bufferbloat(cfg)
    exp.update(r)
    if r.success:
        logger.info(
            "bufferbloat ok: idle p50 {:.0f}ms  down p50 {:.0f}ms (+{:.0f})  "
            "up p50 {:.0f}ms (+{:.0f})  grade {}",
            r.idle["p50"] * 1000,
            r.loaded_down["p50"] * 1000,
            r.increase_down * 1000,
            r.loaded_up["p50"] * 1000,
            r.increase_up * 1000,
            grade(max(r.increase_down, r.increase_up))[0],
        )
    else:
        logger.warning("bufferbloat failed: {}", r.error or "no samples")


async def collect_once(cfg: BufferbloatConfig, exp: BufferbloatExporter) -> None:
    import asyncio

    await asyncio.to_thread(collect_sync, cfg, exp)
