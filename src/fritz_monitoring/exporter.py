"""
Prometheus exporter for Fritz!Box metrics
"""

from prometheus_client import Counter, Gauge, Histogram, generate_latest, CollectorRegistry
from datetime import datetime
from typing import Dict, Any
from loguru import logger


class FritzBoxExporter:
    """Exports Fritz!Box metrics to Prometheus"""

    def __init__(self):
        """Initialize exporter with Prometheus metrics"""
        self.registry = CollectorRegistry()

        # Connection metrics
        self.wan_ip = Gauge(
            "fritzbox_wan_ip",
            "WAN IP address (as hash for label compatibility)",
            registry=self.registry,
        )
        self.downstream_speed = Gauge(
            "fritzbox_downstream_speed_mbs",
            "Downstream speed in Mbps",
            registry=self.registry,
        )
        self.upstream_speed = Gauge(
            "fritzbox_upstream_speed_mbs",
            "Upstream speed in Mbps",
            registry=self.registry,
        )
        self.connected = Gauge(
            "fritzbox_connected",
            "Connection status (1=connected, 0=disconnected)",
            registry=self.registry,
        )
        self.bytes_sent = Gauge(
            "fritzbox_bytes_sent_total",
            "Total bytes sent",
            registry=self.registry,
        )
        self.bytes_received = Gauge(
            "fritzbox_bytes_received_total",
            "Total bytes received",
            registry=self.registry,
        )

        # Device metrics
        self.device_count = Gauge(
            "fritzbox_connected_devices",
            "Number of connected devices",
            registry=self.registry,
        )
        self.wlan_associated_devices = Gauge(
            "fritzbox_wlan_associated_devices",
            "Number of associated WLAN devices",
            registry=self.registry,
        )

        # System metrics
        self.uptime_seconds = Gauge(
            "fritzbox_uptime_seconds",
            "Fritz!Box uptime in seconds",
            registry=self.registry,
        )

        # Scrape metrics
        self.scrape_duration = Histogram(
            "fritzbox_scrape_duration_seconds",
            "Time spent scraping Fritz!Box",
            registry=self.registry,
        )
        self.scrape_errors = Counter(
            "fritzbox_scrape_errors_total",
            "Total number of scrape errors",
            registry=self.registry,
        )

    def export(self, metrics: Dict[str, Any]) -> None:
        """Update Prometheus metrics from collected data"""
        try:
            # Connection metrics
            conn = metrics.get("connection", {})
            if conn.get("downstream_speed_mbs"):
                self.downstream_speed.set(conn["downstream_speed_mbs"])
            if conn.get("upstream_speed_mbs"):
                self.upstream_speed.set(conn["upstream_speed_mbs"])
            if "connected" in conn:
                self.connected.set(1 if conn["connected"] else 0)
            if conn.get("bytes_sent"):
                self.bytes_sent.set(conn["bytes_sent"])
            if conn.get("bytes_received"):
                self.bytes_received.set(conn["bytes_received"])

            # Device metrics
            devices = metrics.get("devices", {})
            self.device_count.set(devices.get("device_count", 0))

            # WLAN metrics
            wlan = metrics.get("wlan", {})
            if "associated_devices" in wlan:
                self.wlan_associated_devices.set(wlan["associated_devices"])

            # System metrics
            system = metrics.get("system", {})
            if system.get("uptime_seconds"):
                self.uptime_seconds.set(system["uptime_seconds"])

            logger.debug("Metrics exported successfully")

        except Exception as e:
            logger.error(f"Error exporting metrics: {e}")
            self.scrape_errors.inc()
            raise

    def get_metrics(self) -> bytes:
        """Get Prometheus formatted metrics"""
        return generate_latest(self.registry)
