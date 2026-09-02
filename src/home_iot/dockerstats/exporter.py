"""Docker containers -> Prometheus, straight off the Engine API socket.

:func:`cpu_percent` and :func:`parse_stats` are pure (they take the JSON the
Docker API returns) so they are unit-testable without a daemon.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from ..common import env_float, env_str

INTERVAL_FLOOR_S = 10.0


@dataclass(frozen=True)
class DockerStatsConfig:
    #: unix socket path, or "tcp://host:port" for a docker-socket-proxy
    socket_path: str = "/var/run/docker.sock"
    interval_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "DockerStatsConfig":
        # DOCKER_HOST wins (set to tcp://docker-socket-proxy:2375 by compose)
        target = env_str("DOCKER_HOST") or env_str(
            "DOCKER_SOCKET", "/var/run/docker.sock"
        )
        return cls(
            socket_path=target,
            interval_seconds=env_float(
                "DOCKERSTATS_INTERVAL_SECONDS", 20.0, floor=INTERVAL_FLOOR_S
            ),
        )


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float = 10.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._unix_path = path

    def connect(self) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._unix_path)
        self.sock = s


def _connection(target: str, timeout: float) -> http.client.HTTPConnection:
    if target.startswith(("tcp://", "http://")):
        host = target.split("://", 1)[1]
        h, _, p = host.partition(":")
        return http.client.HTTPConnection(h, int(p or 2375), timeout=timeout)
    return _UnixHTTPConnection(target, timeout=timeout)


def _api_get(socket_path: str, path: str, timeout: float = 10.0) -> Any:
    conn = _connection(socket_path, timeout)
    try:
        conn.request(
            "GET", path, headers={"Host": "localhost", "Accept": "application/json"}
        )
        resp = conn.getresponse()
        body = resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"Docker API {path} -> {resp.status}")
        return json.loads(body or b"null")
    finally:
        conn.close()


@dataclass
class ContainerStat:
    name: str
    state: str
    health: int  # 1 healthy, 0 unhealthy, -1 none/unknown
    restart_count: int
    cpu_percent: float
    mem_bytes: float
    mem_limit_bytes: float
    net_rx_bytes: float
    net_tx_bytes: float


def cpu_percent(stats: Dict[str, Any]) -> float:
    """Docker's own cpu-% formula (delta cpu / delta system * ncpu * 100)."""
    try:
        cpu = stats["cpu_stats"]
        pre = stats["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        ncpu = cpu.get("online_cpus") or len(
            cpu["cpu_usage"].get("percpu_usage") or [1]
        )
        if cpu_delta > 0 and sys_delta > 0:
            return round(cpu_delta / sys_delta * ncpu * 100.0, 2)
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return 0.0


def _health(container: Dict[str, Any]) -> int:
    """Health from a /containers/json entry.

    The list endpoint has no ``Health`` object; the health shows up as a
    ``(healthy)`` / ``(unhealthy)`` suffix on the ``Status`` string. The detail
    endpoint (``State`` = dict) is also accepted for the unit tests.
    """
    state = container.get("State")
    if isinstance(state, dict):
        h = (state.get("Health") or {}).get("Status")
        return 1 if h == "healthy" else 0 if h in ("unhealthy", "starting") else -1
    status = str(container.get("Status", ""))
    if "(healthy)" in status:
        return 1
    if "(unhealthy)" in status or "(health: starting)" in status:
        return 0
    return -1


def _running(container: Dict[str, Any]) -> str:
    state = container.get("State")
    if isinstance(state, dict):
        return (
            "running"
            if state.get("Running") or state.get("Status") == "running"
            else "stopped"
        )
    return str(state or "")


def parse_stats(
    container: Dict[str, Any], stats: Dict[str, Any], restart_count: int = 0
) -> ContainerStat:
    names = container.get("Names") or [container.get("Name", "")]
    name = (names[0] if names else "").lstrip("/")
    mem = stats.get("memory_stats") or {}
    usage = float(mem.get("usage", 0) or 0)
    # exclude page cache the way `docker stats` does
    cache = float((mem.get("stats") or {}).get("inactive_file", 0) or 0)
    rx = tx = 0.0
    for iface in (stats.get("networks") or {}).values():
        rx += float(iface.get("rx_bytes", 0) or 0)
        tx += float(iface.get("tx_bytes", 0) or 0)
    return ContainerStat(
        name=name,
        state=_running(container),
        health=_health(container),
        restart_count=int(restart_count or container.get("RestartCount", 0) or 0),
        cpu_percent=cpu_percent(stats),
        mem_bytes=max(0.0, usage - cache),
        mem_limit_bytes=float(mem.get("limit", 0) or 0),
        net_rx_bytes=rx,
        net_tx_bytes=tx,
    )


class DockerStatsExporter:
    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        def g(name: str, doc: str, labels: tuple = ()) -> Gauge:
            return Gauge(name, doc, labels, registry=self.registry)

        self.up = g("dockerstats_up", "1 if the last Docker API poll succeeded")
        self.last_ts = g(
            "dockerstats_last_scrape_timestamp_seconds", "Unix time of last poll"
        )
        self.count = g("dockerstats_container_count", "Running containers seen")

        lbl = ("name",)
        self.c_up = g("docker_container_up", "1 if the container is running", lbl)
        self.c_health = g(
            "docker_container_health", "1 healthy / 0 unhealthy / -1 none", lbl
        )
        self.c_restarts = g(
            "docker_container_restart_count", "Lifetime restart count", lbl
        )
        self.c_cpu = g(
            "docker_container_cpu_percent",
            "CPU usage (percent of one core * ncpu)",
            lbl,
        )
        self.c_mem = g("docker_container_memory_bytes", "Memory working set", lbl)
        self.c_mem_lim = g(
            "docker_container_memory_limit_bytes", "Memory limit (0 = none)", lbl
        )
        self.c_rx = g(
            "docker_container_network_receive_bytes_total", "NIC rx bytes", lbl
        )
        self.c_tx = g(
            "docker_container_network_transmit_bytes_total", "NIC tx bytes", lbl
        )

    def update(self, stats: Optional[List[ContainerStat]], *, ok: bool) -> None:
        self.up.set(1 if ok else 0)
        self.last_ts.set(time.time())
        for m in (
            self.c_up,
            self.c_health,
            self.c_restarts,
            self.c_cpu,
            self.c_mem,
            self.c_mem_lim,
            self.c_rx,
            self.c_tx,
        ):
            m.clear()
        if stats is None or not ok:
            return
        self.count.set(len(stats))
        for s in stats:
            self.c_up.labels(s.name).set(1 if s.state == "running" else 0)
            self.c_health.labels(s.name).set(s.health)
            self.c_restarts.labels(s.name).set(s.restart_count)
            self.c_cpu.labels(s.name).set(s.cpu_percent)
            self.c_mem.labels(s.name).set(s.mem_bytes)
            self.c_mem_lim.labels(s.name).set(s.mem_limit_bytes)
            self.c_rx.labels(s.name).set(s.net_rx_bytes)
            self.c_tx.labels(s.name).set(s.net_tx_bytes)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def _one(socket_path: str, c: Dict[str, Any]) -> Optional[ContainerStat]:
    cid = c.get("Id")
    if not cid:
        return None
    try:
        st = _api_get(socket_path, f"/v1.43/containers/{cid}/stats?stream=false")
        restart = 0
        try:  # list entry has no RestartCount; only the detail endpoint does
            detail = _api_get(socket_path, f"/v1.43/containers/{cid}/json")
            restart = int(detail.get("RestartCount", 0) or 0)
        except Exception:  # noqa: BLE001
            pass
        return parse_stats(c, st, restart_count=restart)
    except Exception as exc:  # noqa: BLE001 - one bad container must not kill the poll
        logger.debug("stats for {} failed: {}", str(cid)[:12], exc)
        return None


def collect_sync(cfg: DockerStatsConfig, exp: DockerStatsExporter) -> None:
    from concurrent.futures import ThreadPoolExecutor

    try:
        containers = _api_get(cfg.socket_path, "/v1.43/containers/json?all=false") or []
        # /stats?stream=false blocks ~1s per container while Docker samples CPU;
        # fan out so a 25-container stack polls in a few seconds, not a minute.
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = pool.map(lambda c: _one(cfg.socket_path, c), containers)
        out = [r for r in results if r is not None]
        exp.update(out, ok=True)
        logger.info("dockerstats ok: {} container(s)", len(out))
    except Exception as exc:  # noqa: BLE001
        exp.update(None, ok=False)
        logger.warning("dockerstats poll failed: {}", exc)


async def collect_once(cfg: DockerStatsConfig, exp: DockerStatsExporter) -> None:
    await asyncio.to_thread(collect_sync, cfg, exp)
