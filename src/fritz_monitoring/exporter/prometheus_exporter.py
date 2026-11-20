"""Prometheus exporter for Fritz!Box metrics using atomic background snapshots."""
from datetime import datetime, timezone
from typing import Optional
from prometheus_client import CollectorRegistry, Gauge, Counter, generate_latest

from ..collector import CollectorService, MonitoringSnapshot, CollectorState


class FritzPrometheusExporter:
    """Exporter rendering Prometheus metrics from MonitoringSnapshot."""

    def __init__(self, collector_service: Optional[CollectorService] = None) -> None:
        self.collector_service = collector_service
        self.registry = CollectorRegistry()

        # Exporter Self-Metrics
        self.scrape_success = Gauge(
            "fritz_scrape_success",
            "1 if the last snapshot collection succeeded, 0 otherwise",
            registry=self.registry,
        )
        self.scrape_duration_seconds = Gauge(
            "fritz_scrape_duration_seconds",
            "Duration of the last snapshot collection in seconds",
            registry=self.registry,
        )
        self.scrape_errors_total = Counter(
            "fritz_scrape_errors_total",
            "Total number of collection errors by type",
            ["type"],
            registry=self.registry,
        )
        self.last_success_timestamp_seconds = Gauge(
            "fritz_last_success_timestamp_seconds",
            "Timestamp of the last successful collection pass",
            registry=self.registry,
        )
        self.consecutive_scrape_failures = Gauge(
            "fritz_consecutive_scrape_failures",
            "Number of consecutive collection failures",
            registry=self.registry,
        )
        self.snapshot_age_seconds = Gauge(
            "fritz_snapshot_age_seconds",
            "Age of the current snapshot in seconds",
            registry=self.registry,
        )
        self.exporter_build_info = Gauge(
            "fritz_exporter_build_info",
            "Fritz Exporter build and version info",
            ["version"],
            registry=self.registry,
        )
        self.exporter_build_info.labels(version="1.0.0").set(1)

        # Persistent registry of known mesh nodes across snapshots
        self._known_mesh_nodes: dict[str, dict[str, Any]] = {}

        if self.collector_service is not None:
            self.collector_service.on_error_callback = (
                lambda err_type: self.scrape_errors_total.labels(type=err_type).inc()
            )

        # Router WAN Metrics
        self.router_bytes_received_total = Gauge(
            "fritz_router_bytes_received_total",
            "Total WAN bytes received",
            registry=self.registry,
        )
        self.router_bytes_sent_total = Gauge(
            "fritz_router_bytes_sent_total",
            "Total WAN bytes sent",
            registry=self.registry,
        )
        self.router_uptime_seconds = Gauge(
            "fritz_router_uptime_seconds",
            "Router uptime in seconds",
            registry=self.registry,
        )
        self.router_max_byte_rate_up = Gauge(
            "fritz_router_max_byte_rate_up",
            "Maximum upload byte rate",
            registry=self.registry,
        )
        self.router_max_byte_rate_down = Gauge(
            "fritz_router_max_byte_rate_down",
            "Maximum download byte rate",
            registry=self.registry,
        )
        self.router_current_bytes_received_rate = Gauge(
            "fritz_router_current_bytes_received_rate",
            "Current download rate in bytes/sec",
            registry=self.registry,
        )
        self.router_current_bytes_sent_rate = Gauge(
            "fritz_router_current_bytes_sent_rate",
            "Current upload rate in bytes/sec",
            registry=self.registry,
        )
        self.router_connection_uptime_seconds = Gauge(
            "fritz_router_connection_uptime_seconds",
            "WAN connection uptime in seconds",
            registry=self.registry,
        )
        self.router_is_connected = Gauge(
            "fritz_router_is_connected",
            "1 if WAN is connected, 0 otherwise",
            registry=self.registry,
        )
        self.router_external_ip = Gauge(
            "fritz_router_external_ip",
            "External IP address as info metric",
            ["ip"],
            registry=self.registry,
        )

        # DSL Line Quality Metrics
        self.router_dsl_downstream_attenuation = Gauge(
            "fritz_router_dsl_downstream_attenuation",
            "DSL downstream attenuation in dB",
            registry=self.registry,
        )
        self.router_dsl_upstream_attenuation = Gauge(
            "fritz_router_dsl_upstream_attenuation",
            "DSL upstream attenuation in dB",
            registry=self.registry,
        )
        self.router_dsl_downstream_noise_margin = Gauge(
            "fritz_router_dsl_downstream_noise_margin",
            "DSL downstream noise margin in dB",
            registry=self.registry,
        )
        self.router_dsl_upstream_noise_margin = Gauge(
            "fritz_router_dsl_upstream_noise_margin",
            "DSL upstream noise margin in dB",
            registry=self.registry,
        )

        # System Metrics
        self.router_cpu_temperature = Gauge(
            "fritz_router_cpu_temperature_celsius",
            "CPU temperature in Celsius",
            ["cpu"],
            registry=self.registry,
        )

        # Device Count Metrics
        self.total_devices = Gauge(
            "fritz_total_devices",
            "Total number of known devices",
            registry=self.registry,
        )
        self.online_devices = Gauge(
            "fritz_online_devices",
            "Number of currently online devices",
            registry=self.registry,
        )
        self.offline_devices = Gauge(
            "fritz_offline_devices",
            "Number of offline devices",
            registry=self.registry,
        )

        # WLAN Metrics
        self.wlan_packets_sent_total = Gauge(
            "fritz_wlan_packets_sent_total",
            "Total WiFi packets sent across all interfaces",
            registry=self.registry,
        )
        self.wlan_packets_received_total = Gauge(
            "fritz_wlan_packets_received_total",
            "Total WiFi packets received across all interfaces",
            registry=self.registry,
        )
        self.wlan_channel = Gauge(
            "fritz_wlan_channel",
            "Active Wi-Fi channel (value=1)",
            ["band", "channel"],
            registry=self.registry,
        )
        self.wlan_channel_utilization_percent = Gauge(
            "fritz_wlan_channel_utilization_percent",
            "Wi-Fi channel total utilization percentage",
            ["band", "channel"],
            registry=self.registry,
        )
        self.wlan_non_wifi_interference_percent = Gauge(
            "fritz_wlan_non_wifi_interference_percent",
            "Non-Wi-Fi interference on channel percentage",
            ["band", "channel"],
            registry=self.registry,
        )
        self.wlan_channel_width_mhz = Gauge(
            "fritz_wlan_channel_width_mhz",
            "Wi-Fi channel width in MHz",
            ["band", "channel"],
            registry=self.registry,
        )
        self.wlan_dfs_active = Gauge(
            "fritz_wlan_dfs_active",
            "1 if DFS / weather radar detection wait is active, 0 otherwise",
            ["band"],
            registry=self.registry,
        )

        # Node Metrics
        self.node_up = Gauge(
            "fritz_node_up",
            "1 if node is active, 0 otherwise",
            ["name", "mac", "type"],
            registry=self.registry,
        )
        self.node_info = Gauge(
            "fritz_node_info",
            "Node information with labels (value=1)",
            ["name", "mac", "type", "model", "ip", "parent_name"],
            registry=self.registry,
        )
        self.mesh_node_present = Gauge(
            "fritz_mesh_node_present",
            "1 if mesh node is registered in network inventory",
            ["name", "mac", "type", "model"],
            registry=self.registry,
        )
        self.mesh_node_online = Gauge(
            "fritz_mesh_node_online",
            "1 if mesh node is online/active, 0 if offline or unplugged",
            ["name", "mac", "type"],
            registry=self.registry,
        )
        self.mesh_node_power_state = Gauge(
            "fritz_mesh_node_power_state",
            "Power and connectivity state of the mesh node (1 for active state)",
            ["name", "mac", "type", "state"],
            registry=self.registry,
        )
        self.mesh_node_last_seen_seconds = Gauge(
            "fritz_mesh_node_last_seen_seconds",
            "Unix timestamp when mesh node was last seen online",
            ["name", "mac", "type"],
            registry=self.registry,
        )
        self.node_hop_count = Gauge(
            "fritz_node_hop_count",
            "Hop distance from router in mesh hierarchy (0=router, 1=direct, 2=behind repeater)",
            ["name", "mac", "type"],
            registry=self.registry,
        )
        self.node_link_medium = Gauge(
            "fritz_node_link_medium",
            "Connection medium to mesh parent (value=1)",
            ["name", "mac", "type", "medium"],
            registry=self.registry,
        )
        self.node_link_quality_ratio = Gauge(
            "fritz_node_link_quality_ratio",
            "Ratio of current link speed to expected link speed (0.0 - 1.0)",
            ["name", "mac", "type"],
            registry=self.registry,
        )

        # Device Metrics
        dev_labels = [
            "mac",
            "name",
            "ip",
            "node",
            "node_mac",
            "interface",
            "repeater",
            "powerline",
        ]
        self.device_up = Gauge(
            "fritz_device_up",
            "1 if device is online, 0 otherwise",
            dev_labels,
            registry=self.registry,
        )
        self.device_rx_bytes_total = Gauge(
            "fritz_device_rx_bytes_total",
            "Total bytes received per device",
            dev_labels,
            registry=self.registry,
        )
        self.device_tx_bytes_total = Gauge(
            "fritz_device_tx_bytes_total",
            "Total bytes transmitted per device",
            dev_labels,
            registry=self.registry,
        )

        # WLAN Device Metrics
        wlan_labels = ["mac", "name", "ip", "node", "node_mac"]
        self.device_wlan_signal_strength = Gauge(
            "fritz_device_wlan_signal_strength",
            "WLAN signal strength percentage (0-100)",
            wlan_labels,
            registry=self.registry,
        )
        self.device_wlan_speed_mbps = Gauge(
            "fritz_device_wlan_speed_mbps",
            "WLAN connection speed in Mbps",
            wlan_labels,
            registry=self.registry,
        )

        # Node Link Speeds & Traffic
        self.node_link_rx_kbps = Gauge(
            "fritz_node_link_rx_kbps",
            "Current download link speed in kbps for mesh node",
            ["name", "mac", "type"],
            registry=self.registry,
        )
        self.node_link_tx_kbps = Gauge(
            "fritz_node_link_tx_kbps",
            "Current upload link speed in kbps for mesh node",
            ["name", "mac", "type"],
            registry=self.registry,
        )

        # Per-node connected device counts and mesh hierarchy
        self.repeater_connected_devices = Gauge(
            "fritz_repeater_connected_devices",
            "Number of devices connected to this repeater",
            ["name", "mac"],
            registry=self.registry,
        )
        self.powerline_connected_devices = Gauge(
            "fritz_powerline_connected_devices",
            "Number of devices connected to this powerline node",
            ["name", "mac"],
            registry=self.registry,
        )
        self.node_parent = Gauge(
            "fritz_node_parent",
            "Mesh parent relationship (value=1); parent_* empty for the router",
            ["name", "mac", "parent_name", "parent_mac"],
            registry=self.registry,
        )

        # Permission-gated FRITZ!Box features (1 = available to the monitoring
        # account, 0 = withheld — see docs/fritz-permissions.md).
        self.capability_available = Gauge(
            "fritz_capability_available",
            "1 if the FRITZ!Box exposes this feature to the monitoring account",
            ["feature"],
            registry=self.registry,
        )

        # Port Forwarding & UPnP IGD Metrics
        self.port_mapping_entry = Gauge(
            "fritz_port_mapping_entry",
            "Active port mapping on WAN interface (value=1)",
            ["port", "protocol", "internal_client", "internal_port", "description", "is_upnp"],
            registry=self.registry,
        )
        self.total_port_mappings = Gauge(
            "fritz_total_port_mappings",
            "Total number of active port mappings",
            registry=self.registry,
        )
        self.upnp_port_mappings = Gauge(
            "fritz_upnp_port_mappings",
            "Number of dynamically opened UPnP port mappings",
            registry=self.registry,
        )

        # VoIP / SIP Telephony Metrics
        self.voip_number_registered = Gauge(
            "fritz_voip_number_registered",
            "1 if the VoIP phone number is registered with provider, 0 otherwise",
            ["number"],
            registry=self.registry,
        )
        self.voip_total_numbers = Gauge(
            "fritz_voip_total_numbers",
            "Total configured VoIP telephone numbers",
            registry=self.registry,
        )
        self.voip_registered_numbers = Gauge(
            "fritz_voip_registered_numbers",
            "Number of currently successfully registered VoIP numbers",
            registry=self.registry,
        )

    def render_snapshot(
        self,
        snapshot: Optional[MonitoringSnapshot],
        state: Optional[CollectorState] = None,
    ) -> None:
        """Update metric values based on snapshot and collector state without exporting fake zeros."""
        now = datetime.now(timezone.utc)

        if state is not None:
            c_state = state
            success = (
                1 if c_state.consecutive_failures == 0 and snapshot is not None else 0
            )
            self.scrape_success.set(success)
            self.consecutive_scrape_failures.set(c_state.consecutive_failures)

            if c_state.last_success:
                ts = c_state.last_success.timestamp()
                self.last_success_timestamp_seconds.set(ts)
                self.snapshot_age_seconds.set(
                    max(0.0, (now - c_state.last_success).total_seconds())
                )

        if snapshot is None:
            self.scrape_success.set(0)
            return

        self.scrape_duration_seconds.set(snapshot.collection_duration_seconds)

        # Clear info/label metrics to prevent staleness
        self.router_external_ip.clear()
        self.router_cpu_temperature.clear()

        # WAN Stats - Omit sample if value is None
        wan = snapshot.wan
        if wan:
            if wan.total_bytes_received is not None:
                self.router_bytes_received_total.set(wan.total_bytes_received)
            if wan.total_bytes_sent is not None:
                self.router_bytes_sent_total.set(wan.total_bytes_sent)
            if wan.device_uptime is not None:
                self.router_uptime_seconds.set(wan.device_uptime)
            if wan.max_upstream_rate is not None:
                self.router_max_byte_rate_up.set(wan.max_upstream_rate)
            if wan.max_downstream_rate is not None:
                self.router_max_byte_rate_down.set(wan.max_downstream_rate)
            if wan.current_download_rate is not None:
                self.router_current_bytes_received_rate.set(wan.current_download_rate)
            if wan.current_upload_rate is not None:
                self.router_current_bytes_sent_rate.set(wan.current_upload_rate)
            if wan.connection_uptime is not None:
                self.router_connection_uptime_seconds.set(wan.connection_uptime)
            if wan.is_connected is not None:
                self.router_is_connected.set(1 if wan.is_connected else 0)

            if wan.external_ip:
                self.router_external_ip.labels(ip=wan.external_ip).set(1)

            for cpu_name, temp in wan.cpu_temperatures.items():
                if temp is not None:
                    self.router_cpu_temperature.labels(cpu=cpu_name).set(temp)

        # DSL Stats - Omit sample if value is None
        dsl = snapshot.dsl
        if dsl:
            if dsl.downstream_attenuation is not None:
                self.router_dsl_downstream_attenuation.set(dsl.downstream_attenuation)
            if dsl.upstream_attenuation is not None:
                self.router_dsl_upstream_attenuation.set(dsl.upstream_attenuation)
            if dsl.downstream_noise_margin is not None:
                self.router_dsl_downstream_noise_margin.set(dsl.downstream_noise_margin)
            if dsl.upstream_noise_margin is not None:
                self.router_dsl_upstream_noise_margin.set(dsl.upstream_noise_margin)

        # WLAN Stats - Omit sample if value is None
        wlan = snapshot.wlan
        if wlan:
            if wlan.total_packets_sent is not None:
                self.wlan_packets_sent_total.set(wlan.total_packets_sent)
            if wlan.total_packets_received is not None:
                self.wlan_packets_received_total.set(wlan.total_packets_received)

        # Wi-Fi Spectrum & Channel Info
        self.wlan_channel.clear()
        self.wlan_channel_utilization_percent.clear()
        self.wlan_non_wifi_interference_percent.clear()
        self.wlan_channel_width_mhz.clear()
        self.wlan_dfs_active.clear()

        for ch in getattr(snapshot, "wlan_channels", ()):
            self.wlan_channel.labels(band=ch.band, channel=str(ch.channel)).set(1)
            self.wlan_channel_utilization_percent.labels(
                band=ch.band, channel=str(ch.channel)
            ).set(ch.utilization_percent)
            self.wlan_non_wifi_interference_percent.labels(
                band=ch.band, channel=str(ch.channel)
            ).set(ch.interference_percent)
            self.wlan_channel_width_mhz.labels(
                band=ch.band, channel=str(ch.channel)
            ).set(ch.channel_width_mhz)
            self.wlan_dfs_active.labels(band=ch.band).set(1 if ch.dfs_wait_active else 0)

        # Device Counts
        devices = snapshot.devices
        total_count = len(devices)
        online_count = sum(1 for d in devices if d.is_active)
        offline_count = total_count - online_count

        self.total_devices.set(total_count)
        self.online_devices.set(online_count)
        self.offline_devices.set(offline_count)

        # Port Forwarding & UPnP IGD Mappings
        self.port_mapping_entry.clear()
        port_mappings = getattr(snapshot, "port_mappings", ())
        self.total_port_mappings.set(len(port_mappings))
        upnp_count = sum(1 for p in port_mappings if p.is_upnp)
        self.upnp_port_mappings.set(upnp_count)

        for pm in port_mappings:
            self.port_mapping_entry.labels(
                port=str(pm.external_port),
                protocol=pm.protocol,
                internal_client=pm.internal_client,
                internal_port=str(pm.internal_port),
                description=pm.description,
                is_upnp="true" if pm.is_upnp else "false",
            ).set(1 if pm.enabled else 0)

        # VoIP / Telephony Numbers
        self.voip_number_registered.clear()
        voip_nums = getattr(snapshot, "voip_numbers", ())
        self.voip_total_numbers.set(len(voip_nums))
        reg_count = sum(1 for v in voip_nums if v.is_registered)
        self.voip_registered_numbers.set(reg_count)

        for vn in voip_nums:
            self.voip_number_registered.labels(number=vn.number).set(
                1 if vn.is_registered else 0
            )

        # Render Nodes & Mesh Inventory
        self.node_up.clear()
        self.node_info.clear()
        self.node_link_rx_kbps.clear()
        self.node_link_tx_kbps.clear()
        self.mesh_node_present.clear()
        self.mesh_node_online.clear()
        self.mesh_node_power_state.clear()
        self.mesh_node_last_seen_seconds.clear()
        self.node_hop_count.clear()
        self.node_link_medium.clear()
        self.node_link_quality_ratio.clear()
        self.repeater_connected_devices.clear()
        self.powerline_connected_devices.clear()
        self.node_parent.clear()

        node_name_to_mac = {n.name: n.mac for n in snapshot.mesh_nodes}
        node_name_to_obj = {n.name: n for n in snapshot.mesh_nodes}
        current_macs = set()

        # Build parent hierarchy mapping for multi-hop depth
        parent_map: dict[str, str] = {}
        for n in snapshot.mesh_nodes:
            if n.parent_node:
                parent_map[n.name] = n.parent_node

        def _calc_hop(name: str, depth: int = 0) -> int:
            if depth > 5 or name not in parent_map:
                return depth
            return _calc_hop(parent_map[name], depth + 1)

        devices_by_node_name: dict[str, int] = {}
        for dev in devices:
            if dev.connected_to:
                devices_by_node_name[dev.connected_to] = (
                    devices_by_node_name.get(dev.connected_to, 0) + 1
                )

        now_ts = now.timestamp()

        # 1. Update inventory with all nodes currently observed in snapshot
        for node in snapshot.mesh_nodes:
            if node.is_placeholder:
                continue

            mac = (node.mac or "").upper()
            if not mac:
                continue

            current_macs.add(mac)
            node_type = node.kind
            is_active = bool(node.extra.get("active", True))
            model = node.extra.get("model", node.name)
            parent = node.parent_node or ""
            rx_kbps = float(node.extra.get("link_rx_kbps", 0))
            tx_kbps = float(node.extra.get("link_tx_kbps", 0))
            hop = 0 if node.is_router else max(1, _calc_hop(node.name))

            # Detect connection medium
            if node.is_router:
                medium = "direct"
            elif node_type == "powerline":
                medium = "powerline"
            elif rx_kbps >= 800000:
                medium = "lan"
            elif rx_kbps >= 250000:
                medium = "wlan_5ghz"
            else:
                medium = "wlan_2ghz"

            # Compute quality ratio if link exists
            max_kbps = max(rx_kbps, tx_kbps)
            quality_ratio = min(1.0, max_kbps / 1000000.0) if max_kbps > 0 else 0.0

            prev_entry = self._known_mesh_nodes.get(mac, {})
            last_seen = now_ts if is_active else prev_entry.get("last_seen", now_ts)

            self._known_mesh_nodes[mac] = {
                "name": node.name,
                "mac": node.mac,
                "type": node_type,
                "model": model,
                "ip": node.ip or "",
                "parent_name": parent,
                "is_active": is_active,
                "is_router": node.is_router,
                "rx_kbps": rx_kbps,
                "tx_kbps": tx_kbps,
                "hop": hop,
                "medium": medium,
                "quality_ratio": quality_ratio,
                "last_seen": last_seen,
            }

        # 2. Mark any previously known mesh nodes that disappeared as inactive / unpowered
        for mac, kn in self._known_mesh_nodes.items():
            if mac not in current_macs:
                kn["is_active"] = False
                kn["rx_kbps"] = 0.0
                kn["tx_kbps"] = 0.0
                kn["quality_ratio"] = 0.0

        # 3. Render all nodes from inventory
        for kn in self._known_mesh_nodes.values():
            name = kn["name"]
            mac = kn["mac"]
            node_type = kn["type"]
            is_active = kn["is_active"]
            model = kn["model"]
            parent = kn["parent_name"]

            # fritz_node_up: 1 if active, EXPLICIT 0 if offline/unplugged
            self.node_up.labels(name, mac, node_type).set(1 if is_active else 0)
            self.node_info.labels(
                name=name,
                mac=mac,
                type=node_type,
                model=model,
                ip=kn["ip"],
                parent_name=parent,
            ).set(1)

            # Inventory & Power State metrics
            self.mesh_node_present.labels(name, mac, node_type, model).set(1)
            self.mesh_node_online.labels(name, mac, node_type).set(1 if is_active else 0)
            self.mesh_node_power_state.labels(name, mac, node_type, "online").set(
                1 if is_active else 0
            )
            self.mesh_node_power_state.labels(name, mac, node_type, "offline").set(
                0 if is_active else 1
            )
            self.mesh_node_last_seen_seconds.labels(name, mac, node_type).set(
                kn["last_seen"]
            )

            # Link Speeds & Multi-hop Metrics
            self.node_link_rx_kbps.labels(name, mac, node_type).set(kn["rx_kbps"])
            self.node_link_tx_kbps.labels(name, mac, node_type).set(kn["tx_kbps"])
            self.node_hop_count.labels(name, mac, node_type).set(kn["hop"])
            self.node_link_medium.labels(name, mac, node_type, kn["medium"]).set(1)
            self.node_link_quality_ratio.labels(name, mac, node_type).set(
                kn["quality_ratio"]
            )

            if is_active:
                direct_devices = devices_by_node_name.get(name, 0)
                if node_type == "powerline":
                    self.powerline_connected_devices.labels(name, mac).set(direct_devices)
                elif node_type == "repeater":
                    self.repeater_connected_devices.labels(name, mac).set(direct_devices)

                if parent and parent in node_name_to_mac:
                    self.node_parent.labels(
                        name, mac, parent, node_name_to_mac[parent]
                    ).set(1)
                elif kn.get("is_router"):
                    self.node_parent.labels(name, mac, "", "").set(1)

        # Render Devices
        self.device_up.clear()
        self.device_rx_bytes_total.clear()
        self.device_tx_bytes_total.clear()
        self.device_wlan_signal_strength.clear()
        self.device_wlan_speed_mbps.clear()

        for dev in devices:
            node_mac = node_name_to_mac.get(dev.connected_to or "", "")
            connected_obj = node_name_to_obj.get(dev.connected_to or "")

            is_rep = "false"
            is_pwl = "false"
            if connected_obj:
                if connected_obj.kind == "powerline":
                    is_pwl = "true"
                elif connected_obj.kind == "repeater":
                    is_rep = "true"

            dev_args = (
                dev.mac,
                dev.name,
                dev.ip or "",
                dev.connected_to or "",
                node_mac,
                dev.connection_type or "",
                is_rep,
                is_pwl,
            )

            self.device_up.labels(*dev_args).set(1 if dev.is_active else 0)

            if dev.rx_bytes is not None:
                self.device_rx_bytes_total.labels(*dev_args).set(dev.rx_bytes)
            if dev.tx_bytes is not None:
                self.device_tx_bytes_total.labels(*dev_args).set(dev.tx_bytes)

            if dev.connection_type == "802.11" and dev.extra:
                signal = dev.extra.get("signal_strength", 0)
                speed = dev.extra.get("speed", 0)
                wlan_args = (
                    dev.mac,
                    dev.name,
                    dev.ip or "",
                    dev.connected_to or "",
                    node_mac,
                )
                if signal or speed:
                    self.device_wlan_signal_strength.labels(*wlan_args).set(signal)
                    self.device_wlan_speed_mbps.labels(*wlan_args).set(speed)

    def render(self) -> bytes:
        """Collect latest snapshot from CollectorService and generate Prometheus output."""
        if self.collector_service:
            snapshot = self.collector_service.get_snapshot()
            state = self.collector_service.get_state()
            self.render_snapshot(snapshot, state)
            self._render_capabilities()
        return generate_latest(self.registry)

    def _render_capabilities(self) -> None:
        """Expose fritz_capability_available{feature} from the collector probe."""
        get_caps = getattr(self.collector_service, "get_capabilities", None)
        if get_caps is None:
            return
        report = get_caps()
        # fritz-avm-client PermissionReport.as_flags() -> {feature: 1|0}
        flags = getattr(report, "as_flags", None) or getattr(
            report, "as_metric_rows", None
        )
        if flags is None:
            return
        self.capability_available.clear()
        for feature, value in flags().items():
            self.capability_available.labels(feature=feature).set(value)
