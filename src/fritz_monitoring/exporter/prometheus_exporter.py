from prometheus_client import CollectorRegistry, Gauge, generate_latest
from ..avm.models import Node, Device

class FritzPrometheusExporter:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()

        # Router metrics
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

        # DSL line quality metrics
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

        # System metrics (requires authentication)
        self.router_cpu_temperature = Gauge(
            "fritz_router_cpu_temperature_celsius",
            "CPU temperature in Celsius",
            ["cpu"],
            registry=self.registry,
        )

        # Device count metrics
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

        # WLAN interface metrics (works for both router and repeaters)
        self.wlan_packets_sent_total = Gauge(
            "fritz_wlan_packets_sent_total",
            "Total WiFi packets sent across all WLAN interfaces",
            registry=self.registry,
        )
        self.wlan_packets_received_total = Gauge(
            "fritz_wlan_packets_received_total",
            "Total WiFi packets received across all WLAN interfaces",
            registry=self.registry,
        )

        # Node metrics
        self.node_up = Gauge(
            "fritz_node_up",
            "1 if node is active, 0 otherwise",
            ["name", "mac", "type"],
            registry=self.registry,
        )

        self.node_info = Gauge(
            "fritz_node_info",
            "Node information with labels (always 1)",
            ["name", "mac", "type", "model", "ip", "parent_name"],
            registry=self.registry,
        )

        # Device metrics with labels
        labels = ["mac", "name", "ip", "node", "node_mac", "interface", "repeater", "powerline"]
        self.device_up = Gauge(
            "fritz_device_up",
            "1 if device is online, 0 otherwise",
            labels,
            registry=self.registry,
        )
        self.device_rx_bytes_total = Gauge(
            "fritz_device_rx_bytes_total",
            "Total bytes received per device (if supported).",
            labels,
            registry=self.registry,
        )
        self.device_tx_bytes_total = Gauge(
            "fritz_device_tx_bytes_total",
            "Total bytes transmitted per device (if supported).",
            labels,
            registry=self.registry,
        )

        # WLAN device metrics
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

        # Per-repeater connected device count
        self.repeater_connected_devices = Gauge(
            "fritz_repeater_connected_devices",
            "Number of devices connected to this repeater",
            ["name", "mac"],
            registry=self.registry,
        )

        # Per-powerline connected device count
        self.powerline_connected_devices = Gauge(
            "fritz_powerline_connected_devices",
            "Number of devices connected to this powerline node",
            ["name", "mac"],
            registry=self.registry,
        )

        # Node hierarchy and connection metrics
        self.node_parent = Gauge(
            "fritz_node_parent",
            "Parent node relationship (value=1 if this node connects to parent)",
            ["name", "mac", "parent_name", "parent_mac"],
            registry=self.registry,
        )

        self.node_rx_bytes_total = Gauge(
            "fritz_node_rx_bytes_total",
            "Total bytes received by this mesh node from all connected devices",
            ["name", "mac", "type"],
            registry=self.registry,
        )

        self.node_tx_bytes_total = Gauge(
            "fritz_node_tx_bytes_total",
            "Total bytes transmitted by this mesh node to all connected devices",
            ["name", "mac", "type"],
            registry=self.registry,
        )

        self.node_link_rx_kbps = Gauge(
            "fritz_node_link_rx_kbps",
            "Current download rate in kbps for this mesh node's links",
            ["name", "mac", "type"],
            registry=self.registry,
        )

        self.node_link_tx_kbps = Gauge(
            "fritz_node_link_tx_kbps",
            "Current upload rate in kbps for this mesh node's links",
            ["name", "mac", "type"],
            registry=self.registry,
        )

        # Log metrics
        self.log_total = Gauge(
            "fritz_log_total",
            "Total number of log entries",
            registry=self.registry,
        )
        self.log_by_severity = Gauge(
            "fritz_log_by_severity",
            "Number of log entries by severity",
            ["severity"],
            registry=self.registry,
        )
        self.log_by_category = Gauge(
            "fritz_log_by_category",
            "Number of log entries by category",
            ["category"],
            registry=self.registry,
        )
        self.log_by_source = Gauge(
            "fritz_log_by_source",
            "Number of log entries by source device",
            ["source"],
            registry=self.registry,
        )

    def update_from_snapshot(self, router_data, wlan_stats, nodes: list[Node], devices: list[Device]) -> None:
        # Update router metrics
        if router_data:
            self.router_bytes_received_total.set(router_data.get('bytes_received', 0))
            self.router_bytes_sent_total.set(router_data.get('bytes_sent', 0))
            self.router_uptime_seconds.set(router_data.get('uptime', 0))
            self.router_max_byte_rate_up.set(router_data.get('max_byte_rate_up', 0))
            self.router_max_byte_rate_down.set(router_data.get('max_byte_rate_down', 0))

            # New metrics
            self.router_current_bytes_received_rate.set(router_data.get('current_download_rate', 0))
            self.router_current_bytes_sent_rate.set(router_data.get('current_upload_rate', 0))
            self.router_connection_uptime_seconds.set(router_data.get('connection_uptime', 0))
            self.router_is_connected.set(1 if router_data.get('is_connected', False) else 0)

            # External IP as label
            external_ip = router_data.get('external_ip', '')
            if external_ip:
                self.router_external_ip.labels(ip=external_ip).set(1)

            # DSL quality metrics
            self.router_dsl_downstream_attenuation.set(router_data.get('dsl_downstream_attenuation', 0))
            self.router_dsl_upstream_attenuation.set(router_data.get('dsl_upstream_attenuation', 0))
            self.router_dsl_downstream_noise_margin.set(router_data.get('dsl_downstream_noise_margin', 0))
            self.router_dsl_upstream_noise_margin.set(router_data.get('dsl_upstream_noise_margin', 0))

            # CPU temperature
            cpu_temps = router_data.get('cpu_temperatures', {})
            for cpu_name, temp in cpu_temps.items():
                if temp is not None:
                    self.router_cpu_temperature.labels(cpu=cpu_name).set(temp)

        # Device count metrics
        total_count = len(devices)
        online_count = sum(1 for d in devices if d.online)
        offline_count = total_count - online_count

        self.total_devices.set(total_count)
        self.online_devices.set(online_count)
        self.offline_devices.set(offline_count)

        # Update WLAN interface metrics
        if wlan_stats:
            self.wlan_packets_sent_total.set(wlan_stats.get('total_packets_sent', 0))
            self.wlan_packets_received_total.set(wlan_stats.get('total_packets_received', 0))

        # Update node metrics
        for node in nodes:
            node_type = 'router' if node.is_router else ('repeater' if node.is_repeater else 'powerline')
            is_active = node.extra.get('active', True)
            model = node.extra.get('model', node.name)
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

        # Update device metrics
        # Build a map from node name to MAC for quick lookup
        node_name_to_mac = {n.name: n.mac for n in nodes}
        # Build a map from node name to node object for type checking
        node_name_to_obj = {n.name: n for n in nodes}

        for device in devices:
            node_mac = node_name_to_mac.get(device.connected_node, "")
            # Determine if device is connected to a repeater or powerline
            # Priority: router > powerline > repeater (a node can have multiple flags)
            connected_node_obj = node_name_to_obj.get(device.connected_node)
            if connected_node_obj:
                # If connected to router, neither repeater nor powerline flags should be set
                if connected_node_obj.is_router:
                    is_repeater = "false"
                    is_powerline = "false"
                elif connected_node_obj.is_powerline:
                    is_repeater = "false"
                    is_powerline = "true"
                elif connected_node_obj.is_repeater:
                    is_repeater = "true"
                    is_powerline = "false"
                else:
                    is_repeater = "false"
                    is_powerline = "false"
            else:
                is_repeater = "false"
                is_powerline = "false"

            self.device_up.labels(
                device.mac,
                device.name,
                device.ip or "",
                device.connected_node or "",
                node_mac,
                device.interface_type or "",
                is_repeater,
                is_powerline
            ).set(1 if device.online else 0)

            if device.rx_bytes_total is not None:
                self.device_rx_bytes_total.labels(
                    device.mac,
                    device.name,
                    device.ip or "",
                    device.connected_node or "",
                    node_mac,
                    device.interface_type or "",
                    is_repeater,
                    is_powerline
                ).set(device.rx_bytes_total)

            if device.tx_bytes_total is not None:
                self.device_tx_bytes_total.labels(
                    device.mac,
                    device.name,
                    device.ip or "",
                    device.connected_node or "",
                    node_mac,
                    device.interface_type or "",
                    is_repeater,
                    is_powerline
                ).set(device.tx_bytes_total)

            # Export WLAN statistics for WiFi devices
            if device.interface_type == "802.11" and device.extra:
                signal = device.extra.get('signal_strength', 0)
                speed = device.extra.get('speed', 0)
                if signal or speed:
                    self.device_wlan_signal_strength.labels(
                        device.mac,
                        device.name,
                        device.ip or "",
                        device.connected_node or "",
                        node_mac
                    ).set(signal)
                    self.device_wlan_speed_mbps.labels(
                        device.mac,
                        device.name,
                        device.ip or "",
                        device.connected_node or "",
                        node_mac
                    ).set(speed)

        # Update per-repeater counts - grouped by MAC to handle multiple repeaters with same name
        # Build node name -> MAC mapping for accurate counting
        node_name_to_mac_map = {n.name: n.mac for n in nodes}
        node_macs = {n.mac for n in nodes}
        node_names = {n.name for n in nodes}
        mac_to_node_name = {n.mac: n.name for n in nodes}

        # Build mesh hierarchy from node.parent_node
        node_hierarchy = {}  # child_mac -> parent_mac
        nodes_with_parents = 0
        for n in nodes:
            if n.parent_node:
                nodes_with_parents += 1
                if n.parent_node in node_name_to_mac_map:
                    parent_mac = node_name_to_mac_map[n.parent_node]
                    node_hierarchy[n.mac] = parent_mac
                else:
                    print(f"Warning: parent_node '{n.parent_node}' not found for {n.name}")

        print(f"Nodes with parent_node: {nodes_with_parents}, in hierarchy: {len(node_hierarchy)}")
        print(f"Node hierarchy: {node_hierarchy}")

        # Filter out devices that are mesh nodes (by MAC) and deduplicate by MAC
        # Keep only the first occurrence of each MAC (devices can appear multiple times with different connected_nodes)
        seen_macs = set()
        real_devices = []
        router_node_name = next((n.name for n in nodes if n.is_router), "fritz.box")

        for d in devices:
            if d.mac not in node_macs and d.mac not in seen_macs and d.online:
                seen_macs.add(d.mac)  # Mark as seen immediately to avoid duplicates

                # Normalize Device-* or empty connected_node to router
                if not d.connected_node or d.connected_node.startswith("Device-"):
                    # Assign to router
                    from copy import copy
                    d_normalized = copy(d)
                    d_normalized.connected_node = router_node_name
                    real_devices.append(d_normalized)
                else:
                    real_devices.append(d)

        online_count = sum(1 for d in devices if d.online)
        print(f"Total real_devices: {len(real_devices)}, online devices: {online_count}")
        connected_nodes_in_real = set(d.connected_node for d in real_devices if d.connected_node)
        print(f"Connected nodes in real_devices: {connected_nodes_in_real}")
        print(f"Node hierarchy: {node_hierarchy}")

        # Build a function to count devices for a node (DIRECT connections only, no recursion)
        def count_devices_direct(target_mac: str) -> int:
            target_name = mac_to_node_name.get(target_mac, "")
            count = 0
            for d in real_devices:
                if d.connected_node:
                    device_node_mac = node_name_to_mac_map.get(d.connected_node, "")
                    if device_node_mac == target_mac or d.connected_node == target_name:
                        count += 1
            return count

        repeater_nodes = {n.mac: n for n in nodes if n.is_repeater}
        for mac, node in repeater_nodes.items():
            count = count_devices_direct(mac)
            self.repeater_connected_devices.labels(node.name, mac).set(count)

        # Update per-powerline counts - grouped by MAC
        powerline_nodes = {n.mac: n for n in nodes if n.is_powerline}
        for mac, node in powerline_nodes.items():
            count = count_devices_direct(mac)
            self.powerline_connected_devices.labels(node.name, mac).set(count)

        # Export node hierarchy (parent-child relationships)
        for node in nodes:
            if node.parent_node and node.parent_node in node_name_to_mac_map:
                parent_mac = node_name_to_mac_map[node.parent_node]
                self.node_parent.labels(
                    name=node.name,
                    mac=node.mac,
                    parent_name=node.parent_node,
                    parent_mac=parent_mac
                ).set(1)
            elif node.is_router:
                # Root node (fritz.box) has no parent - use empty strings
                self.node_parent.labels(
                    name=node.name,
                    mac=node.mac,
                    parent_name="",
                    parent_mac=""
                ).set(1)

        # Calculate aggregated traffic per node (sum of all connected devices)
        node_traffic = {}  # mac -> {rx: int, tx: int}
        for node in nodes:
            node_traffic[node.mac] = {'rx': 0, 'tx': 0}

        for device in real_devices:
            if device.connected_node and device.connected_node in node_name_to_mac_map:
                node_mac = node_name_to_mac_map[device.connected_node]
                if device.rx_bytes_total:
                    node_traffic[node_mac]['rx'] += device.rx_bytes_total
                if device.tx_bytes_total:
                    node_traffic[node_mac]['tx'] += device.tx_bytes_total

        # Export node traffic metrics
        for node in nodes:
            node_type = 'router' if node.is_router else ('repeater' if node.is_repeater else 'powerline')
            self.node_rx_bytes_total.labels(
                name=node.name,
                mac=node.mac,
                type=node_type
            ).set(node_traffic[node.mac]['rx'])
            self.node_tx_bytes_total.labels(
                name=node.name,
                mac=node.mac,
                type=node_type
            ).set(node_traffic[node.mac]['tx'])

            # Export link speed metrics (current rates in kbps)
            link_rx_kbps = node.extra.get('link_rx_kbps', 0) if node.extra else 0
            link_tx_kbps = node.extra.get('link_tx_kbps', 0) if node.extra else 0
            self.node_link_rx_kbps.labels(
                name=node.name,
                mac=node.mac,
                type=node_type
            ).set(link_rx_kbps)
            self.node_link_tx_kbps.labels(
                name=node.name,
                mac=node.mac,
                type=node_type
            ).set(link_tx_kbps)

    def update_log_metrics(self, log_stats: dict) -> None:
        """Update log-related metrics."""
        # Total logs
        self.log_total.set(log_stats.get('total', 0))

        # Logs by severity
        for severity in ['error', 'warning', 'info']:
            count = log_stats.get(severity, 0)
            self.log_by_severity.labels(severity=severity).set(count)

        # Logs by category
        for category, count in log_stats.get('by_category', {}).items():
            self.log_by_category.labels(category=category).set(count)

        # Logs by source
        for source, count in log_stats.get('by_source', {}).items():
            self.log_by_source.labels(source=source).set(count)

    def render(self) -> bytes:
        return generate_latest(self.registry)
