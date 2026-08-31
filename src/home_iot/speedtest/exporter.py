"""Internet throughput -> Prometheus, via the Cloudflare speed-test endpoints.

No Ookla binary / licence prompt: it just times a large GET from
``speed.cloudflare.com/__down`` and a large POST to ``/__up``, plus a handful of
tiny requests for latency + jitter.

**Bandwidth-heavy** — a run moves ~``SPEEDTEST_MAX_MB`` down and half that up, so
the interval floors at 1800 s and defaults to 3600 s. Opt-in (compose profile
``speedtest``). This complements the always-on WAN byte-rate metrics: those show
*actual usage*, this shows *achievable capacity vs the contract*.

:func:`summarise` is pure (latency list -> min/jitter).
"""
from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass
from typing import List, Optional

import requests
from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float

INTERVAL_FLOOR_S = 1800.0
DOWN_URL = "https://speed.cloudflare.com/__down"
UP_URL = "https://speed.cloudflare.com/__up"
HTTP_TIMEOUT_S = 60.0
LATENCY_SAMPLES = 8


@dataclass(frozen=True)
class SpeedtestConfig:
    interval_seconds: float = 3600.0
    max_mb: int = 100

    @classmethod
    def from_env(cls) -> "SpeedtestConfig":
        return cls(
            interval_seconds=env_float(
                "SPEEDTEST_INTERVAL_SECONDS", 3600.0, floor=INTERVAL_FLOOR_S
            ),
            max_mb=int(env_float("SPEEDTEST_MAX_MB", 100.0, floor=5.0)),
        )


@dataclass
class SpeedtestResult:
    success: bool = False
    download_bps: float = 0.0
    upload_bps: float = 0.0
    latency_s: float = 0.0
    jitter_s: float = 0.0
    bytes_down: int = 0
    bytes_up: int = 0
    error: str = ""


def summarise(latencies: List[float]) -> tuple[float, float]:
    """Return (min latency, jitter=stddev) from per-request round-trip times."""
    clean = [x for x in latencies if x > 0]
    if not clean:
        return 0.0, 0.0
    jitter = statistics.pstdev(clean) if len(clean) > 1 else 0.0
    return min(clean), jitter


def _measure_latency(session: requests.Session) -> tuple[float, float]:
    samples: List[float] = []
    for _ in range(LATENCY_SAMPLES):
        t0 = time.perf_counter()
        try:
            r = session.get(DOWN_URL, params={"bytes": 0}, timeout=10)
            r.raise_for_status()
            samples.append(time.perf_counter() - t0)
        except requests.RequestException:
            pass
    return summarise(samples)


def _measure_download(session: requests.Session, max_bytes: int) -> tuple[int, float]:
    t0 = time.perf_counter()
    got = 0
    with session.get(
        DOWN_URL, params={"bytes": max_bytes}, stream=True, timeout=HTTP_TIMEOUT_S
    ) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=65536):
            got += len(chunk)
    return got, time.perf_counter() - t0


def _measure_upload(session: requests.Session, nbytes: int) -> tuple[int, float]:
    payload = b"\x00" * nbytes
    t0 = time.perf_counter()
    r = session.post(
        UP_URL,
        data=payload,
        timeout=HTTP_TIMEOUT_S,
        headers={"Content-Type": "application/octet-stream"},
    )
    r.raise_for_status()
    return nbytes, time.perf_counter() - t0


def run_speedtest(cfg: SpeedtestConfig) -> SpeedtestResult:
    res = SpeedtestResult()
    session = requests.Session()
    try:
        res.latency_s, res.jitter_s = _measure_latency(session)

        down_bytes = cfg.max_mb * 1024 * 1024
        got, elapsed = _measure_download(session, down_bytes)
        res.bytes_down = got
        if elapsed > 0:
            res.download_bps = got * 8 / elapsed

        up_bytes = max(1, cfg.max_mb // 2) * 1024 * 1024
        sent, elapsed = _measure_upload(session, up_bytes)
        res.bytes_up = sent
        if elapsed > 0:
            res.upload_bps = sent * 8 / elapsed

        res.success = res.download_bps > 0 and res.upload_bps > 0
        return res
    except Exception as exc:  # noqa: BLE001
        res.error = str(exc)
        return res
    finally:
        session.close()


class SpeedtestExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        def g(name: str, doc: str) -> Gauge:
            return Gauge(name, doc, registry=self.registry)

        self.up = g("speedtest_up", "1 if the last run produced a result")
        self.last_ts = g(
            "speedtest_last_run_timestamp_seconds", "Unix time of last run"
        )
        self.download = g(
            "speedtest_download_bits_per_second", "Measured download rate"
        )
        self.upload = g("speedtest_upload_bits_per_second", "Measured upload rate")
        self.latency = g("speedtest_latency_seconds", "Minimum request round-trip time")
        self.jitter = g(
            "speedtest_jitter_seconds", "Round-trip time standard deviation"
        )
        self.bytes_down = g(
            "speedtest_bytes_downloaded", "Bytes moved by the last download test"
        )
        self.bytes_up = g(
            "speedtest_bytes_uploaded", "Bytes moved by the last upload test"
        )

    def update(self, r: SpeedtestResult) -> None:
        self.last_ts.set(time.time())
        self.up.set(1 if r.success else 0)
        if not r.success:
            return
        self.download.set(r.download_bps)
        self.upload.set(r.upload_bps)
        self.latency.set(r.latency_s)
        self.jitter.set(r.jitter_s)
        self.bytes_down.set(r.bytes_down)
        self.bytes_up.set(r.bytes_up)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def collect_sync(cfg: SpeedtestConfig, exp: SpeedtestExporter) -> None:
    logger.info("running Cloudflare speed test (~{} MB down) ...", cfg.max_mb)
    r = run_speedtest(cfg)
    exp.update(r)
    if r.success:
        logger.info(
            "speedtest ok: down={:.1f} Mbit/s up={:.1f} Mbit/s latency={:.0f} ms",
            r.download_bps / 1e6,
            r.upload_bps / 1e6,
            r.latency_s * 1000,
        )
    else:
        logger.warning("speedtest failed: {}", r.error or "no throughput")


async def collect_once(cfg: SpeedtestConfig, exp: SpeedtestExporter) -> None:
    await asyncio.to_thread(collect_sync, cfg, exp)
