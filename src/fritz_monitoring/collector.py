"""Background Collector Service for periodic Fritz!Box snapshot collection."""
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Tuple, Callable
from loguru import logger

from .tracer import trace_span, current_trace_id

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
class WlanChannelInfo:
    """Wi-Fi spectrum, channel load, and interference info per band."""

    band: str
    channel: int
    utilization_percent: float = 0.0
    interference_percent: float = 0.0
    dfs_wait_active: bool = False
    channel_width_mhz: int = 20


@dataclass(frozen=True)
class PortMappingEntry:
    """Active port forwarding mapping (manual or UPnP IGD)."""

    external_port: int
    protocol: str
    internal_client: str
    internal_port: int
    description: str
    enabled: bool
    lease_duration: int
    is_upnp: bool


@dataclass(frozen=True)
class VoipNumberInfo:
    """Configured VoIP / SIP phone number and registration state."""

    number: str
    is_registered: bool
    provider: str = ""


@dataclass(frozen=True)
class MonitoringSnapshot:
    """Immutable snapshot of all collected Fritz!Box monitoring metrics."""

    timestamp: datetime
    wan: Optional[WanStats] = None
    dsl: Optional[DslStats] = None
    wlan: Optional[WlanStats] = None
    wlan_channels: Tuple[WlanChannelInfo, ...] = field(default_factory=tuple)
    port_mappings: Tuple[PortMappingEntry, ...] = field(default_factory=tuple)
    voip_numbers: Tuple[VoipNumberInfo, ...] = field(default_factory=tuple)
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
        self,
        fritz_settings: FritzSettings,
        interval_seconds: float = 30.0,
        emit_events: bool = True,
        emit_device_log: bool = True,
    ) -> None:
        self.fritz_settings = fritz_settings
        self.interval_seconds = interval_seconds
        self._client: Optional[FritzClient] = None

        self._lock = threading.Lock()
        self._snapshot: Optional[MonitoringSnapshot] = None
        self._state = CollectorState()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.on_error_callback: Optional[Callable[[str], None]] = None

        self._event_deriver = None
        if emit_events:
            from .events import EventDeriver

            self._event_deriver = EventDeriver()

        self._device_log = None
        if emit_device_log:
            from .devicelog import DeviceLogTailer

            self._device_log = DeviceLogTailer()

        self._capabilities: Optional[object] = None

    def get_client(self) -> FritzClient:
        """Get or initialize FritzClient instance."""
        if self._client is None:
            self._client = FritzClient(self.fritz_settings)
        return self._client

    def get_capabilities(self) -> Optional[object]:
        """Latest CapabilityReport (None until the first probe)."""
        with self._lock:
            return self._capabilities

    def _probe_capabilities_once(self, client: FritzClient) -> None:
        """Probe the permission-gated FRITZ!Box features once and log a hint.

        Delegates to fritz-avm-client's ``client.probe_capabilities()``; this
        layer only keeps the result and emits one actionable warning.
        """
        if self._capabilities is not None:
            return
        try:
            report = client.probe_capabilities()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Capability probe failed: {exc}")
            return
        with self._lock:
            self._capabilities = report
        denied = getattr(report, "permission_denied", []) or []
        if denied:
            unlocks = getattr(report, "unlocks", {}) or {}
            detail = "; ".join(f"'{f}' (unlocks {unlocks.get(f, '?')})" for f in denied)
            logger.warning(
                "FRITZ!Box is withholding {} feature(s) from the monitoring "
                "account: {}. Grant the user the 'FRITZ!Box Einstellungen' "
                "permission (System > FRITZ!Box-Benutzer). See "
                "docs/fritz-permissions.md.",
                len(denied),
                detail,
            )

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
        """Perform a single collection pass with OpenTelemetry distributed tracing."""
        now = datetime.now(timezone.utc)
        start_time = time.monotonic()

        with self._lock:
            self._state.last_attempt = now

        with trace_span("fritz.collect_cycle") as cycle_span:
            try:
                client = self.get_client()

                with trace_span("fritz.probe_capabilities"):
                    self._probe_capabilities_once(client)

                # WAN & DSL
                with trace_span("fritz.get_wan_dsl"):
                    wan = client.get_wan_stats_typed()
                    dsl = client.router_client.get_dsl_stats()

                # WLAN Multi-band Aggregation & Spectrum Channel Info
                with trace_span("fritz.get_wlan"):
                    wlan_list = client.wlan_client.get_wlan_stats()
                    wlan_channels: list[WlanChannelInfo] = []
                    if wlan_list:
                        clients_list = [
                            w.connected_clients
                            for w in wlan_list
                            if w.connected_clients is not None
                        ]
                        sent_list = [
                            w.total_packets_sent
                            for w in wlan_list
                            if w.total_packets_sent is not None
                        ]
                        recv_list = [
                            w.total_packets_received
                            for w in wlan_list
                            if w.total_packets_received is not None
                        ]
                        ssids = ", ".join(filter(None, [w.ssid for w in wlan_list]))

                        wlan = WlanStats(
                            total_packets_sent=sum(sent_list) if sent_list else None,
                            total_packets_received=sum(recv_list) if recv_list else None,
                            connected_clients=sum(clients_list) if clients_list else None,
                            ssid=ssids or None,
                        )

                        # Extract per-band channel and spectrum interference info
                        fc = getattr(client, "fc", None)
                        for w in wlan_list:
                            idx = getattr(w, "service_index", 1)
                            band = "2.4GHz" if idx == 1 else ("5GHz" if idx == 2 else f"Band{idx}")
                            channel = getattr(w, "channel", 0) or 0
                            util = 0.0
                            interf = 0.0
                            width = 20
                            dfs = False

                            if fc is not None:
                                try:
                                    srv = f"WLANConfiguration{idx}"
                                    if hasattr(fc, "services") and srv in fc.services:
                                        info = fc.call_action(srv, "X_AVM-DE_GetWLANChannelInfo")
                                        util = float(info.get("NewWLANUtilization", 0) or 0)
                                        interf = float(info.get("NewNonWLANInterference", 0) or 0)
                                        width = int(info.get("NewChannelWidth", 20) or 20)
                                        channel = int(info.get("NewChannel", channel) or channel)
                                except Exception:
                                    pass

                            if channel > 0:
                                wlan_channels.append(
                                    WlanChannelInfo(
                                        band=band,
                                        channel=channel,
                                        utilization_percent=util,
                                        interference_percent=interf,
                                        dfs_wait_active=dfs,
                                        channel_width_mhz=width,
                                    )
                                )
                    else:
                        wlan = WlanStats()

                # Mesh Topology & Devices
                with trace_span("fritz.discover_mesh"):
                    mesh_topology = client.discover_mesh()

                # Port Forwarding & UPnP Audit
                port_mappings: list[PortMappingEntry] = []
                with trace_span("fritz.get_port_mappings"):
                    fc = getattr(client, "fc", None)
                    if fc is not None and hasattr(fc, "services"):
                        srv = None
                        for cand in ("WANIPConnection1", "WANPPPConnection1"):
                            if cand in fc.services:
                                srv = cand
                                break
                        if srv:
                            try:
                                num_info = fc.call_action(srv, "GetPortMappingNumberOfEntries")
                                num = int(num_info.get("NewPortMappingNumberOfEntries", 0) or 0)
                                for i in range(min(num, 100)):
                                    try:
                                        p_entry = fc.call_action(
                                            srv, "GetGenericPortMappingEntry", NewPortMappingIndex=i
                                        )
                                        ext_p = int(p_entry.get("NewExternalPort", 0) or 0)
                                        proto = str(p_entry.get("NewPortMappingProtocol", "TCP") or "TCP")
                                        c_ip = str(p_entry.get("NewInternalClient", "") or "")
                                        int_p = int(p_entry.get("NewInternalPort", ext_p) or ext_p)
                                        desc = str(p_entry.get("NewPortMappingDescription", "") or "")
                                        en = bool(p_entry.get("NewEnabled", True))
                                        lease = int(p_entry.get("NewLeaseDuration", 0) or 0)
                                        is_upnp = lease > 0 or any(
                                            kw in desc.lower()
                                            for kw in ("upnp", "miniupnp", "teredo", "xbox", "playstation", "skype")
                                        )
                                        if ext_p > 0:
                                            port_mappings.append(
                                                PortMappingEntry(
                                                    external_port=ext_p,
                                                    protocol=proto,
                                                    internal_client=c_ip,
                                                    internal_port=int_p,
                                                    description=desc,
                                                    enabled=en,
                                                    lease_duration=lease,
                                                    is_upnp=is_upnp,
                                                )
                                            )
                                    except Exception:
                                        break
                            except Exception:
                                pass

                # VoIP / SIP Line Health
                voip_numbers: list[VoipNumberInfo] = []
                with trace_span("fritz.get_voip"):
                    if fc is not None and hasattr(fc, "services") and "X_VoIP1" in fc.services:
                        try:
                            voip_info = None
                            for act in ("X_AVM-DE_GetPhoneNumbers", "X_AVM-DE_GetNumbers"):
                                try:
                                    voip_info = fc.call_action("X_VoIP1", act)
                                    break
                                except Exception:
                                    continue
                            if voip_info:
                                raw_n = (
                                    voip_info.get("NewPhoneNumbers", "")
                                    or voip_info.get("NewNumbers", "")
                                )
                                if isinstance(raw_n, str):
                                    for num_s in raw_n.split(","):
                                        n_clean = num_s.strip()
                                        if n_clean:
                                            voip_numbers.append(
                                                VoipNumberInfo(number=n_clean, is_registered=True)
                                            )
                        except Exception:
                            pass

                duration = time.monotonic() - start_time
                snapshot = MonitoringSnapshot(
                    timestamp=now,
                    wan=wan,
                    dsl=dsl,
                    wlan=wlan,
                    wlan_channels=tuple(wlan_channels),
                    port_mappings=tuple(port_mappings),
                    voip_numbers=tuple(voip_numbers),
                    mesh_nodes=mesh_topology.nodes,
                    devices=mesh_topology.devices,
                    collection_duration_seconds=duration,
                )

                with self._lock:
                    self._snapshot = snapshot
                    self._state.last_success = now
                    self._state.consecutive_failures = 0
                    self._state.last_error_type = None

                tid = current_trace_id() or "none"
                logger.info(
                    f"Successfully collected Fritz!Box snapshot in {duration:.2f}s "
                    f"({len(snapshot.mesh_nodes)} nodes, {len(snapshot.devices)} devices) trace_id={tid}"
                )

                # Derive structured events from the state transition. Never let an
                # error here disrupt collection.
                if self._event_deriver is not None:
                    try:
                        with trace_span("fritz.derive_events"):
                            self._event_deriver.process(snapshot)
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.warning(f"Event derivation failed: {exc}")

                if self._device_log is not None:
                    try:
                        with trace_span("fritz.device_log_poll"):
                            self._device_log.poll(self.get_client())
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.warning(f"Device-log tailing failed: {exc}")

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
        if hasattr(self, "on_error_callback") and callable(self.on_error_callback):
            try:
                self.on_error_callback(error_type)
            except Exception as cb_err:
                logger.warning(f"Error in on_error_callback: {cb_err}")
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
