"""
Fritz!Box data collector using fritzconnection library
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from fritzconnection.lib.fritzwlan import FritzWLAN
from fritzconnection.lib.fritzstatus import FritzStatus
from fritzconnection.lib.fritzdevicemanager import FritzDeviceManager
from loguru import logger


class FritzBoxCollector:
    """Collects metrics from Fritz!Box"""

    def __init__(self, host: str, username: str, password: str, port: int = 49000):
        """Initialize Fritz!Box collector"""
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.address = f"http://{host}:{port}"
        self._status: Optional[FritzStatus] = None
        self._wlan: Optional[FritzWLAN] = None
        self._device_manager: Optional[FritzDeviceManager] = None

    async def connect(self) -> None:
        """Connect to Fritz!Box"""
        try:
            await asyncio.to_thread(self._connect_sync)
            logger.info(f"Connected to Fritz!Box at {self.address}")
        except Exception as e:
            logger.error(f"Failed to connect to Fritz!Box: {e}")
            raise

    def _connect_sync(self) -> None:
        """Synchronous connection (to be run in thread pool)"""
        try:
            self._status = FritzStatus(address=self.address, username=self.username, password=self.password)
            self._wlan = FritzWLAN(address=self.address, username=self.username, password=self.password)
            self._device_manager = FritzDeviceManager(address=self.address, username=self.username, password=self.password)
        except Exception as e:
            logger.error(f"Connection initialization failed: {e}")
            raise

    async def collect_metrics(self) -> Dict[str, Any]:
        """Collect all metrics from Fritz!Box"""
        if not self._status:
            await self.connect()

        metrics = {}
        try:
            metrics["timestamp"] = datetime.now().isoformat()
            metrics["connection"] = await self._collect_connection_metrics()
            metrics["devices"] = await self._collect_device_metrics()
            metrics["wlan"] = await self._collect_wlan_metrics()
            metrics["system"] = await self._collect_system_metrics()
        except Exception as e:
            logger.error(f"Failed to collect metrics: {e}")
            raise

        return metrics

    async def _collect_connection_metrics(self) -> Dict[str, Any]:
        """Collect WAN connection metrics"""
        return await asyncio.to_thread(self._collect_connection_metrics_sync)

    def _collect_connection_metrics_sync(self) -> Dict[str, Any]:
        """Synchronous connection metrics collection"""
        if not self._status:
            return {}

        return {
            "wan_ip": self._status.wan_ip,
            "downstream_speed_mbs": self._status.downstream_speed_mbs,
            "upstream_speed_mbs": self._status.upstream_speed_mbs,
            "connection_status": self._status.connection_status,
            "connected": self._status.connected,
            "is_connected": self._status.is_connected,
            "bytes_sent": self._status.bytes_sent,
            "bytes_received": self._status.bytes_received,
        }

    async def _collect_device_metrics(self) -> Dict[str, Any]:
        """Collect connected device metrics"""
        return await asyncio.to_thread(self._collect_device_metrics_sync)

    def _collect_device_metrics_sync(self) -> Dict[str, Any]:
        """Synchronous device metrics collection"""
        if not self._device_manager:
            return {"devices": [], "device_count": 0}

        devices = []
        for device in self._device_manager.devices:
            devices.append({
                "name": device.friendly_name,
                "ip": device.ip_address,
                "mac": device.mac_address,
                "model": device.model_name,
                "connected": device.connected,
            })

        return {
            "devices": devices,
            "device_count": len(devices),
        }

    async def _collect_wlan_metrics(self) -> Dict[str, Any]:
        """Collect WLAN metrics"""
        return await asyncio.to_thread(self._collect_wlan_metrics_sync)

    def _collect_wlan_metrics_sync(self) -> Dict[str, Any]:
        """Synchronous WLAN metrics collection"""
        if not self._wlan:
            return {}

        try:
            return {
                "wlan_enabled": self._wlan.wlan_enabled,
                "associated_devices": self._wlan.associated_devices,
            }
        except Exception as e:
            logger.warning(f"Could not collect WLAN metrics: {e}")
            return {}

    async def _collect_system_metrics(self) -> Dict[str, Any]:
        """Collect system metrics"""
        return await asyncio.to_thread(self._collect_system_metrics_sync)

    def _collect_system_metrics_sync(self) -> Dict[str, Any]:
        """Synchronous system metrics collection"""
        if not self._status:
            return {}

        return {
            "model": self._status.model,
            "serial": self._status.serialnumber,
            "fw_version": self._status.fw_version,
            "uptime_seconds": self._status.uptime,
        }
