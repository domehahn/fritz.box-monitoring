"""iperf3 runner + Prometheus exposition. Pure-ish core is `parse_iperf_json`."""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

INTERVAL_FLOOR = 600.0
DURATION_CAP = 30.0


@dataclass
class IperfConfig:
    target: Optional[str]
    port: int = 5201
    interval_seconds: float = 21600.0
    duration_seconds: float = 5.0
    bitrate: str = ""  # e.g. "100M"; empty = unlimited
    reverse: bool = False  # also measure download (server -> client)

    @classmethod
    def from_env(cls) -> "IperfConfig":
        return cls(
            target=os.getenv("IPERF_TARGET") or None,
            port=int(os.getenv("IPERF_PORT", "5201")),
            interval_seconds=max(
                INTERVAL_FLOOR, float(os.getenv("IPERF_INTERVAL_SECONDS", "21600"))
            ),
            duration_seconds=min(
                DURATION_CAP, float(os.getenv("IPERF_DURATION_SECONDS", "5"))
            ),
            bitrate=os.getenv("IPERF_BITRATE", ""),
            reverse=os.getenv("IPERF_REVERSE", "false").lower() in ("1", "true", "yes"),
        )


@dataclass
class IperfResult:
    success: bool
    sent_bps: float = 0.0
    received_bps: float = 0.0
    retransmits: float = 0.0
    error: str = ""


def parse_iperf_json(payload: Dict[str, Any]) -> IperfResult:
    """Extract throughput/retransmits from an ``iperf3 --json`` document."""
    if payload.get("error"):
        return IperfResult(success=False, error=str(payload["error"]))
    end = payload.get("end", {})
    sent = end.get("sum_sent", {}) or {}
    recv = end.get("sum_received", {}) or {}
    return IperfResult(
        success=True,
        sent_bps=float(sent.get("bits_per_second", 0.0) or 0.0),
        received_bps=float(recv.get("bits_per_second", 0.0) or 0.0),
        retransmits=float(sent.get("retransmits", 0.0) or 0.0),
    )


async def run_iperf(cfg: IperfConfig) -> IperfResult:
    if not cfg.target:
        return IperfResult(success=False, error="IPERF_TARGET not set")
    args = [
        "iperf3",
        "-c",
        cfg.target,
        "-p",
        str(cfg.port),
        "-t",
        str(int(cfg.duration_seconds)),
        "-J",
    ]
    if cfg.bitrate:
        args += ["-b", cfg.bitrate]
    if cfg.reverse:
        args += ["-R"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(
            proc.communicate(), timeout=cfg.duration_seconds + 30
        )
    except FileNotFoundError:
        return IperfResult(success=False, error="iperf3 binary not found")
    except asyncio.TimeoutError:
        return IperfResult(success=False, error="iperf3 timed out")
    try:
        return parse_iperf_json(json.loads(out.decode() or "{}"))
    except Exception as exc:  # noqa: BLE001
        return IperfResult(
            success=False, error=f"parse failed: {exc}; stderr={err.decode()[:200]}"
        )


class IperfExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()
        g = lambda n, d: Gauge(n, d, registry=self.registry)  # noqa: E731
        self.enabled = g("iperf_enabled", "1 if IPERF_TARGET is configured")
        self.last_success = g("iperf_last_run_success", "1 if the last run succeeded")
        self.last_ts = g(
            "iperf_last_run_timestamp_seconds", "Unix time of the last run"
        )
        self.sent = g(
            "iperf_sent_bits_per_second", "Upload throughput (client->server)"
        )
        self.received = g(
            "iperf_received_bits_per_second", "Download throughput (server->client)"
        )
        self.retransmits = g("iperf_retransmits", "TCP retransmits in the last run")

    def update(self, result: IperfResult, enabled: bool) -> None:
        self.enabled.set(1 if enabled else 0)
        self.last_ts.set(time.time())
        self.last_success.set(1 if result.success else 0)
        if result.success:
            self.sent.set(result.sent_bps)
            self.received.set(result.received_bps)
            self.retransmits.set(result.retransmits)

    def render(self) -> bytes:
        return generate_latest(self.registry)


async def _loop(cfg: IperfConfig, exp: IperfExporter) -> None:
    while True:
        if cfg.target:
            logger.info(f"Running iperf3 against {cfg.target}:{cfg.port} ...")
            res = await run_iperf(cfg)
            exp.update(res, enabled=True)
            if res.success:
                logger.info(
                    "iperf3 ok: up={:.1f} Mbit/s down={:.1f} Mbit/s retransmits={}",
                    res.sent_bps / 1e6,
                    res.received_bps / 1e6,
                    res.retransmits,
                )
            else:
                logger.warning(f"iperf3 failed: {res.error}")
        else:
            exp.update(IperfResult(success=False), enabled=False)
        await asyncio.sleep(cfg.interval_seconds)
