"""Background Collector Service for periodic Fritz!Box snapshot collection."""
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Tuple
from loguru import logger

from fritz_avm_client import (
    FritzClient,
    Settings as FritzSettings,
    WanStats,
    DslStats,
    WlanStats,
    Node,
    Device,
    FritzError,
    FritzTimeoutError,
    FritzConnectionError,
    FritzAuthenticationError,
)


@dataclass(frozen=True)
class MonitoringSnapshot:
    """Immutable snapshot of all collected Fritz!Box monitoring metrics."""

    timestamp: datetime
    wan: Optional[WanStats] = None
    dsl: Optional[DslStats] = None
    wlan: Optional[WlanStats] = None
    mesh_nodes: Tuple[Node, ...] = field(default_factory=tuple)
    devices: Tuple[Device, ...] = field(default_factory=tuple)
    collection_duration_seconds: float = 0.0


@dataclass
class CollectorState:
    """Operational health state of the background collector."""

    last_attempt: Optional[datetime] = None
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0
    last_error_type: Optional[str] = None


class CollectorService:
    """Background service that periodically collects snapshots from Fritz!Box."""

    def __init__(
        self, fritz_settings: FritzSettings, interval_seconds: float = 30.0
    ) -> None:
        self.fritz_settings = fritz_settings
        self.interval_seconds = interval_seconds
        self._client: Optional[FritzClient] = None

        self._lock = threading.Lock()
        self._snapshot: Optional[MonitoringSnapshot] = None
        self._state = CollectorState()

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def get_client(self) -> FritzClient:
        """Get or initialize FritzClient instance."""
        if self._client is None:
            self._client = FritzClient(self.fritz_settings)
        return self._client

    def get_snapshot(self) -> Optional[MonitoringSnapshot]:
        """Thread-safe retrieval of the latest snapshot."""
        with self._lock:
            return self._snapshot

    def get_state(self) -> CollectorState:
        """Thread-safe retrieval of the collector operational state."""
        with self._lock:
            return CollectorState(
                last_attempt=self._state.last_attempt,
                last_success=self._state.last_success,
                consecutive_failures=self._state.consecutive_failures,
                last_error_type=self._state.last_error_type,
            )

    def collect_once(self) -> MonitoringSnapshot:
        """Perform a single collection pass."""
        now = datetime.now(timezone.utc)
        start_time = time.monotonic()

        with self._lock:
            self._state.last_attempt = now

        try:
            client = self.get_client()

            # WAN & DSL
            wan = client.get_wan_stats_typed()
            dsl = client.router_client.get_dsl_stats()

            # WLAN
            wlan_list = client.wlan_client.get_wlan_stats()
            wlan = wlan_list[0] if wlan_list else WlanStats()

            # Mesh Topology & Devices
            mesh_topology = client.discover_mesh()

            duration = time.monotonic() - start_time
            snapshot = MonitoringSnapshot(
                timestamp=now,
                wan=wan,
                dsl=dsl,
                wlan=wlan,
                mesh_nodes=mesh_topology.nodes,
                devices=mesh_topology.devices,
                collection_duration_seconds=duration,
            )

            with self._lock:
                self._snapshot = snapshot
                self._state.last_success = now
                self._state.consecutive_failures = 0
                self._state.last_error_type = None

            logger.info(
                f"Successfully collected Fritz!Box snapshot in {duration:.2f}s "
                f"({len(snapshot.mesh_nodes)} nodes, {len(snapshot.devices)} devices)"
            )
            return snapshot

        except FritzTimeoutError as exc:
            self._record_error("timeout", exc)
            raise
        except FritzAuthenticationError as exc:
            self._record_error("authentication_error", exc)
            raise
        except FritzConnectionError as exc:
            self._record_error("connection_error", exc)
            raise
        except FritzError as exc:
            self._record_error("fritz_error", exc)
            raise
        except Exception as exc:
            self._record_error("unknown_error", exc)
            raise

    def _record_error(self, error_type: str, exc: Exception) -> None:
        """Record an error in collector state."""
        with self._lock:
            self._state.consecutive_failures += 1
            self._state.last_error_type = error_type
        logger.warning(f"Snapshot collection failed ({error_type}): {exc}")

    def _run_loop(self) -> None:
        """Main loop executing periodic snapshot collections."""
        logger.info(
            f"Starting CollectorService loop (interval: {self.interval_seconds}s)"
        )
        while self._running:
            try:
                self.collect_once()
            except Exception:
                pass  # Errors logged in _record_error, loop continues

            # Sleep in small increments for fast SIGTERM/stop responsiveness
            sleep_remaining = self.interval_seconds
            while self._running and sleep_remaining > 0:
                time.sleep(min(1.0, sleep_remaining))
                sleep_remaining -= 1.0

        logger.info("CollectorService loop stopped")

    def start(self) -> None:
        """Start the background collector thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, name="CollectorServiceThread", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Gracefully stop the background collector thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
