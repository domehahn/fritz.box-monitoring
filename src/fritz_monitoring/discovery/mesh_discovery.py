#!/usr/bin/env python3
"""
Fritz!Box Mesh Discovery Service
Automatically discovers all mesh nodes and updates Prometheus targets
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List

from fritzconnection import FritzConnection
from fritzconnection.lib.fritzhosts import FritzHosts

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MeshDiscovery:
    """Discovers Fritz!Box mesh topology and generates Prometheus targets"""

    def __init__(self, fritz_host: str, fritz_port: int, username: str, password: str):
        self.fritz_host = fritz_host
        self.fritz_port = fritz_port
        self.username = username
        self.password = password
        self.targets_file = Path("/prometheus/targets/mesh-targets.json")

        # Initialize Fritz!Box connection
        self.fc = FritzConnection(
            address=fritz_host,
            port=fritz_port,
            user=username,
            password=password
        )
        self.hosts = FritzHosts(self.fc)

    def discover_mesh_nodes(self) -> List[Dict]:
        """Query Fritz!Box for mesh topology and return list of targets"""
        try:
            logger.info(f"Fetching mesh topology from {self.fritz_host}:{self.fritz_port}")

            # Get mesh topology using FritzHosts
            mesh_info = self.hosts.get_mesh_topology()

            if not mesh_info or 'nodes' not in mesh_info:
                logger.warning("No mesh topology data received")
                return []

            targets = []
            nodes = mesh_info.get('nodes', [])

            logger.info(f"Found {len(nodes)} mesh nodes")

            for node in nodes:
                device_name = node.get('device_name', 'unknown')
                device_mac = node.get('device_mac_address', '')
                device_ip = node.get('device_ip_address', '')
                node_type = node.get('node_type', 'unknown')

                # Skip if no IP address (offline or not accessible)
                if not device_ip or device_ip == '0.0.0.0':
                    logger.debug(f"Skipping {device_name} - no valid IP address")
                    continue

                # Create target for this mesh node
                target = {
                    "targets": [f"{device_ip}:49000"],
                    "labels": {
                        "job": "fritz_mesh",
                        "device_name": device_name,
                        "device_mac": device_mac,
                        "device_ip": device_ip,
                        "node_type": node_type,
                        "__param_target": device_ip
                    }
                }

                targets.append(target)
                logger.info(f"Added target: {device_name} ({device_ip}) - Type: {node_type}")

            # Always add the main router as a target
            router_target = {
                "targets": [f"{self.fritz_host}:{self.fritz_port}"],
                "labels": {
                    "job": "fritz_router",
                    "device_name": "fritz.box",
                    "device_ip": self.fritz_host,
                    "node_type": "router",
                    "__param_target": self.fritz_host
                }
            }
            targets.append(router_target)
            logger.info(f"Added router target: {self.fritz_host}")

            return targets

        except Exception as e:
            logger.error(f"Error discovering mesh nodes: {e}", exc_info=True)
            return []

    def write_targets_file(self, targets: List[Dict]):
        """Write targets to JSON file for Prometheus file_sd_configs"""
        try:
            # Ensure directory exists
            self.targets_file.parent.mkdir(parents=True, exist_ok=True)

            # Write targets file
            with open(self.targets_file, 'w') as f:
                json.dump(targets, f, indent=2)

            logger.info(f"Wrote {len(targets)} targets to {self.targets_file}")

        except Exception as e:
            logger.error(f"Error writing targets file: {e}", exc_info=True)

    def run_discovery(self):
        """Run discovery once"""
        logger.info("Starting mesh discovery...")
        targets = self.discover_mesh_nodes()

        if targets:
            self.write_targets_file(targets)
            logger.info(f"Discovery complete: {len(targets)} targets")
        else:
            logger.warning("No targets discovered")

    def run_continuous(self, interval: int = 300):
        """Run discovery continuously at specified interval (seconds)"""
        logger.info(f"Starting continuous discovery (interval: {interval}s)")

        while True:
            try:
                self.run_discovery()
            except Exception as e:
                logger.error(f"Error in discovery loop: {e}", exc_info=True)

            logger.info(f"Sleeping for {interval} seconds...")
            time.sleep(interval)


def main():
    """Main entry point"""
    # Get configuration from environment
    fritz_host = os.getenv('FRITZ_HOST', '192.168.178.1')
    fritz_port = int(os.getenv('FRITZ_PORT', '49000'))
    username = os.getenv('FRITZ_USERNAME', '')
    password = os.getenv('FRITZ_PASSWORD', '')
    discovery_interval = int(os.getenv('DISCOVERY_INTERVAL', '300'))  # 5 minutes default

    if not password:
        logger.error("FRITZ_PASSWORD environment variable not set!")
        return

    # Create discovery service
    discovery = MeshDiscovery(
        fritz_host=fritz_host,
        fritz_port=fritz_port,
        username=username,
        password=password
    )

    # Run discovery
    discovery.run_continuous(interval=discovery_interval)


if __name__ == '__main__':
    main()
