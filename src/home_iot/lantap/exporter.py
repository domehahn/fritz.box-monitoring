"""Per-device up/down byte accounting from a live FRITZ!Box packet capture.

The FRITZ!Box can stream a continuous pcap of one of its interfaces
(``/cgi-bin/capture_notimeout``). Tapping the LAN bridge and bucketing
``orig_len`` by the local source / destination IP gives real per-device
throughput — the one thing TR-064 does not expose.

**This loads the FRITZ!Box's CPU** (AVM does not support 24/7 capture). It is
opt-in (compose profile ``lantap``), uses a small snaplen, and honours
``LANTAP_MAX_MINUTES`` for an automatic stop.

Counters only ever increase (a Prometheus ``Counter``); ``rate()`` in the
dashboard turns them into bit/s.
"""
from __future__ import annotations

import ipaddress
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

from loguru import logger
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

from ..common import env_float, env_str, read_secret
from .login import check_session, login
from .pcap import Net, PcapStream, classify


@dataclass(frozen=True)
class LanTapConfig:
    host: str
    username: str
    password: str
    iface: str = "1-lan"
    snaplen: int = 128
    subnets: str = "192.168.178.0/24"
    max_minutes: float = 0.0
    reresolve_seconds: float = 60.0

    @property
    def configured(self) -> bool:
        return bool(self.host and self.username and self.password)

    @property
    def nets(self) -> List[Net]:
        out: List[Net] = []
        for c in self.subnets.split(","):
            c = c.strip()
            if c:
                out.append(ipaddress.ip_network(c, strict=False))
        return out

    @classmethod
    def from_env(cls) -> "LanTapConfig":
        return cls(
            host=env_str("FRITZ_HOST", "192.168.178.1"),
            username=env_str("FRITZ_USERNAME") or env_str("FRITZ_ADMIN_USERNAME"),
            password=read_secret(
                env_str("FRITZ_PASSWORD_FILE") or env_str("FRITZ_PASSWORD")
            ),
            iface=env_str("LANTAP_IFACE", "1-lan"),
            snaplen=int(env_float("LANTAP_SNAPLEN", 128.0, floor=64.0)),
            subnets=env_str("LANTAP_SUBNETS", "192.168.178.0/24"),
            max_minutes=env_float("LANTAP_MAX_MINUTES", 0.0),
            reresolve_seconds=env_float("LANTAP_RERESOLVE_SECONDS", 60.0, floor=15.0),
        )


class LanTapExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.up = Gauge(
            "lantap_up", "1 while the capture is streaming", registry=self.registry
        )
        self.configured = Gauge(
            "lantap_configured", "1 if FRITZ creds are set", registry=self.registry
        )
        self.frames = Counter(
            "lantap_frames_total", "Frames parsed", registry=self.registry
        )
        self.parse_errors = Counter(
            "lantap_parse_errors_total",
            "Pcap desyncs / re-syncs",
            registry=self.registry,
        )
        self.sent = Counter(
            "lantap_host_sent_bytes_total",
            "Bytes a local host sent (upload)",
            ["ip"],
            registry=self.registry,
        )
        self.recv = Counter(
            "lantap_host_received_bytes_total",
            "Bytes a local host received (download)",
            ["ip"],
            registry=self.registry,
        )
        self.sent_pkts = Counter(
            "lantap_host_sent_packets_total",
            "Packets a local host sent",
            ["ip"],
            registry=self.registry,
        )
        self.recv_pkts = Counter(
            "lantap_host_received_packets_total",
            "Packets a local host received",
            ["ip"],
            registry=self.registry,
        )
        self.info = Gauge(
            "lantap_host_info",
            "Host identity",
            ["ip", "name", "mac"],
            registry=self.registry,
        )

    def add(self, ip: str, direction: str, nbytes: int) -> None:
        if direction == "tx":
            self.sent.labels(ip).inc(nbytes)
            self.sent_pkts.labels(ip).inc()
        else:
            self.recv.labels(ip).inc(nbytes)
            self.recv_pkts.labels(ip).inc()

    def set_names(self, mapping: Dict[str, tuple]) -> None:
        self.info.clear()
        for ip, (name, mac) in mapping.items():
            self.info.labels(ip, name or ip, mac or "").set(1)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def _resolve_hosts(cfg: LanTapConfig) -> Dict[str, tuple]:
    """ip -> (name, mac) via fritz-avm-client, best effort."""
    try:
        from fritz_avm_client import FritzClient, Settings

        client = FritzClient(
            Settings(
                fritz_host=cfg.host,
                fritz_username=cfg.username,
                fritz_password=cfg.password,
            )
        )
        out: Dict[str, tuple] = {}
        for h in client.get_all_hosts() or []:
            ip = getattr(h, "ip", "") or (h.get("ip") if isinstance(h, dict) else "")
            if not ip:
                continue
            name = getattr(h, "name", "") or (
                h.get("name") if isinstance(h, dict) else ""
            )
            mac = getattr(h, "mac", "") or (h.get("mac") if isinstance(h, dict) else "")
            out[ip] = (name, mac)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("host resolve failed: {}", exc)
        return {}


def capture_loop(cfg: LanTapConfig, exp: LanTapExporter, stop: threading.Event) -> None:
    """Stream the capture, accounting bytes, until ``stop`` or ``max_minutes``."""
    exp.configured.set(1 if cfg.configured else 0)
    if not cfg.configured:
        exp.up.set(0)
        return
    nets = cfg.nets
    deadline = time.time() + cfg.max_minutes * 60 if cfg.max_minutes else 0.0
    next_resolve = 0.0
    sid = ""

    while not stop.is_set():
        if deadline and time.time() > deadline:
            logger.warning("LANTAP_MAX_MINUTES reached — stopping capture")
            break
        try:
            if not sid or not check_session(cfg.host, sid):
                sid = login(cfg.host, cfg.username, cfg.password)
                logger.info("FRITZ!Box UI session established")
            url = (
                f"http://{cfg.host}/cgi-bin/capture_notimeout"
                f"?ifaceorminor={cfg.iface}&snaplen={cfg.snaplen}"
                f"&capture=Start&sid={sid}"
            )
            resp = urllib.request.urlopen(url, timeout=15)
            exp.up.set(1)
            logger.info("capturing {} (snaplen {})", cfg.iface, cfg.snaplen)
            stream = PcapStream()
            while not stop.is_set():
                if deadline and time.time() > deadline:
                    break
                chunk = resp.read(65536)
                if not chunk:
                    break
                try:
                    for orig_len, frame in stream.feed(chunk):
                        exp.frames.inc()
                        for ip, direction, n in classify(frame, orig_len, nets):
                            exp.add(ip, direction, n)
                except Exception as exc:  # noqa: BLE001 - resync on desync
                    exp.parse_errors.inc()
                    logger.warning("pcap parse error, resyncing: {}", exc)
                    stream = PcapStream()
                if time.time() > next_resolve:
                    exp.set_names(_resolve_hosts(cfg))
                    next_resolve = time.time() + cfg.reresolve_seconds
        except PermissionError as exc:
            logger.error(str(exc))
            exp.up.set(0)
            stop.wait(30)
        except Exception as exc:  # noqa: BLE001
            logger.warning("capture stream ended ({}); reconnecting", exc)
            exp.up.set(0)
            sid = ""
            stop.wait(5)
    exp.up.set(0)
    logger.info("capture loop stopped")
