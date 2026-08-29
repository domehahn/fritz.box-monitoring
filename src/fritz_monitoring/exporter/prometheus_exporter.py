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

        # Device Metrics
        dev_labels = ["mac", "name", "ip", "node", "node_mac", "interface", "repeater", "powerline"]
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

    def render_snapshot(self, snapshot: Optional[MonitoringSnapshot], state: Optional[CollectorState] = None) -> None:
        """Update metric values based on snapshot and collector state."""
        now = datetime.now(timezone.utc)

        if state is not None:
            c_state = state
            success = 1 if c_state.consecutive_failures == 0 and snapshot is not None else 0
            self.scrape_success.set(success)
            self.consecutive_scrape_failures.set(c_state.consecutive_failures)

            if c_state.last_success:
                ts = c_state.last_success.timestamp()
                self.last_success_timestamp_seconds.set(ts)
                self.snapshot_age_seconds.set(max(0.0, (now - c_state.last_success).total_seconds()))

        if snapshot is None:
            self.scrape_success.set(0)
            return

        self.scrape_duration_seconds.set(snapshot.collection_duration_seconds)

        # WAN Stats
        wan = snapshot.wan
        if wan:
            self.router_bytes_received_total.set(wan.total_bytes_received or 0)
            self.router_bytes_sent_total.set(wan.total_bytes_sent or 0)
            self.router_uptime_seconds.set(wan.device_uptime or 0)
            self.router_max_byte_rate_up.set(wan.max_upstream_rate or 0)
            self.router_max_byte_rate_down.set(wan.max_downstream_rate or 0)
            self.router_current_bytes_received_rate.set(wan.current_download_rate or 0)
            self.router_current_bytes_sent_rate.set(wan.current_upload_rate or 0)
            self.router_connection_uptime_seconds.set(wan.connection_uptime or 0)
            self.router_is_connected.set(1 if wan.is_connected else 0)

            if wan.external_ip:
                self.router_external_ip.clear()
                self.router_external_ip.labels(ip=wan.external_ip).set(1)

            for cpu_name, temp in wan.cpu_temperatures.items():
                if temp is not None:
                    self.router_cpu_temperature.labels(cpu=cpu_name).set(temp)

        # DSL Stats
        dsl = snapshot.dsl
        if dsl:
            self.router_dsl_downstream_attenuation.set(dsl.downstream_attenuation or 0.0)
            self.router_dsl_upstream_attenuation.set(dsl.upstream_attenuation or 0.0)
            self.router_dsl_downstream_noise_margin.set(dsl.downstream_noise_margin or 0.0)
            self.router_dsl_upstream_noise_margin.set(dsl.upstream_noise_margin or 0.0)

        # WLAN Stats
        wlan = snapshot.wlan
        if wlan:
            self.wlan_packets_sent_total.set(wlan.total_packets_sent)
            self.wlan_packets_received_total.set(wlan.total_packets_received)

        # Device Counts
        devices = snapshot.devices
        total_count = len(devices)
        online_count = sum(1 for d in devices if d.is_active)
        offline_count = total_count - online_count

        self.total_devices.set(total_count)
        self.online_devices.set(online_count)
        self.offline_devices.set(offline_count)

        # Render Nodes
        self.node_up.clear()
        self.node_info.clear()
        self.node_link_rx_kbps.clear()
        self.node_link_tx_kbps.clear()

        node_name_to_mac = {n.name: n.mac for n in snapshot.mesh_nodes}
        node_name_to_obj = {n.name: n for n in snapshot.mesh_nodes}

        for node in snapshot.mesh_nodes:
            node_type = "router" if node.is_router else ("powerline" if node.is_powerline else "repeater")
            is_active = node.extra.get("active", True)
            model = node.extra.get("model", node.name)
            parent = node.parent_node or ""

            self.node_up.labels(node.name, node.mac, node_type).set(1 if is_active else 0)
            self.node_info.labels(
                name=node.name,
                mac=node.mac,
                type=node_type,
                model=model,
                ip=node.ip or "",
                parent_name=parent
            ).set(1)

            rx_kbps = node.extra.get("link_rx_kbps", 0)
            tx_kbps = node.extra.get("link_tx_kbps", 0)
            self.node_link_rx_kbps.labels(node.name, node.mac, node_type).set(rx_kbps)
            self.node_link_tx_kbps.labels(node.name, node.mac, node_type).set(tx_kbps)

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
                if connected_obj.is_powerline:
                    is_pwl = "true"
                elif connected_obj.is_repeater and not connected_obj.is_router:
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
                wlan_args = (dev.mac, dev.name, dev.ip or "", dev.connected_to or "", node_mac)
                if signal or speed:
                    self.device_wlan_signal_strength.labels(*wlan_args).set(signal)
                    self.device_wlan_speed_mbps.labels(*wlan_args).set(speed)

    def render(self) -> bytes:
        """Collect latest snapshot from CollectorService and generate Prometheus output."""
        if self.collector_service:
            snapshot = self.collector_service.get_snapshot()
            state = self.collector_service.get_state()
            self.render_snapshot(snapshot, state)
        return generate_latest(self.registry)
