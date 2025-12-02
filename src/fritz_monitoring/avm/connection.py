from fritzconnection import FritzConnection
from fritzconnection.lib.fritzhosts import FritzHosts
from fritzconnection.lib.fritzstatus import FritzStatus
from fritzconnection.lib.fritzwlan import FritzWLAN
from ..config import Settings

class FritzClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.fc = FritzConnection(
            address=settings.fritz_host,
            port=settings.fritz_port,
            user=settings.fritz_username,
            password=settings.fritz_password,
        )
        self.hosts = FritzHosts(self.fc)
        self.status = FritzStatus(self.fc)
        self.wlan = FritzWLAN(self.fc)

    def get_all_hosts(self):
        """Get all hosts from Fritz!Box"""
        return self.hosts.get_hosts_info()

    def get_mesh_info(self):
        """Get mesh topology information"""
        try:
            return self.hosts.get_mesh_topology()
        except Exception:
            return None

    def get_device_stats(self, mac_address):
        """Get traffic statistics for a specific device by MAC address"""
        try:
            # Try to get device-specific statistics
            result = self.fc.call_action('Hosts1', 'GetSpecificHostEntry', NewMACAddress=mac_address)
            return {
                'rx_bytes': result.get('NewX_AVM-DE_RxBytes', 0),
                'tx_bytes': result.get('NewX_AVM-DE_TxBytes', 0),
            }
        except Exception:
            return {'rx_bytes': 0, 'tx_bytes': 0}

    def get_wan_stats(self):
        """Get WAN statistics including real-time rates and connection info"""
        try:
            # Get current transmission rates (bytes/sec)
            current_rates = self.status.transmission_rate  # Returns (downstream, upstream) in bytes/sec
            
            # Get connection uptime (different from device uptime)
            connection_uptime = getattr(self.status, 'connection_uptime', 0)
            
            # Get external IP
            external_ip = getattr(self.status, 'external_ip', '')
            
            # Get DSL line quality metrics
            attenuation = self.status.attenuation  # Returns (downstream, upstream) in dB
            noise_margin = self.status.noise_margin  # Returns (downstream, upstream) in dB
            
            return {
                'bytes_sent': self.status.bytes_sent or 0,
                'bytes_received': self.status.bytes_received or 0,
                'max_byte_rate_up': self.status.max_byte_rate[1] if self.status.max_byte_rate else 0,
                'max_byte_rate_down': self.status.max_byte_rate[0] if self.status.max_byte_rate else 0,
                'current_download_rate': current_rates[0] if current_rates else 0,
                'current_upload_rate': current_rates[1] if current_rates else 0,
                'uptime': getattr(self.status, 'device_uptime', 0),
                'connection_uptime': connection_uptime,
                'is_connected': self.status.is_connected,
                'external_ip': external_ip,
                'dsl_downstream_attenuation': attenuation[0] if attenuation else 0,
                'dsl_upstream_attenuation': attenuation[1] if attenuation else 0,
                'dsl_downstream_noise_margin': noise_margin[0] if noise_margin else 0,
                'dsl_upstream_noise_margin': noise_margin[1] if noise_margin else 0,
                'cpu_temperatures': self._get_cpu_temperatures(),
            }
        except Exception as e:
            print(f"Error getting WAN stats: {e}")
            return {
                'bytes_sent': 0,
                'bytes_received': 0,
                'max_byte_rate_up': 0,
                'max_byte_rate_down': 0,
                'current_download_rate': 0,
                'current_upload_rate': 0,
                'uptime': 0,
                'connection_uptime': 0,
                'is_connected': False,
                'external_ip': '',
                'dsl_downstream_attenuation': 0,
                'dsl_upstream_attenuation': 0,
                'dsl_downstream_noise_margin': 0,
                'dsl_upstream_noise_margin': 0,
                'cpu_temperatures': {},
            }
    
    def _get_cpu_temperatures(self):
        """Get CPU temperature readings (requires authentication)"""
        try:
            temps = self.status.get_cpu_temperatures()
            if temps:
                # Convert to dict format: {cpu_name: temperature}
                result = {}
                for i, temp in enumerate(temps):
                    result[f'cpu{i}'] = temp
                return result
        except Exception as e:
            # Not all Fritz!Box models support temperature readings
            # or authentication might be required
            pass
        return {}
    
    def get_wlan_traffic_stats(self):
        """Get WiFi interface traffic statistics (works on repeaters too)"""
        wlan_stats = {}
        try:
            # Query all WLAN configuration services
            for service_id in range(1, 5):
                try:
                    service_name = f'WLANConfiguration{service_id}'
                    
                    # Get statistics for this WLAN interface
                    result = self.fc.call_action(service_name, 'GetStatistics')
                    
                    # Aggregate all interfaces
                    if service_id == 1:
                        wlan_stats = {
                            'total_packets_sent': result.get('NewTotalPacketsSent', 0),
                            'total_packets_received': result.get('NewTotalPacketsReceived', 0),
                        }
                    else:
                        wlan_stats['total_packets_sent'] += result.get('NewTotalPacketsSent', 0)
                        wlan_stats['total_packets_received'] += result.get('NewTotalPacketsReceived', 0)
                        
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"Error getting WLAN stats: {e}")
            
        return wlan_stats

    def get_wlan_devices(self):
        """Get all devices connected via WLAN with their associated access point MAC"""
        wlan_devices = []
        try:
            # Query all WLAN configuration services (typically 1-4 for different bands/SSIDs)
            for service_id in range(1, 5):
                try:
                    service_name = f'WLANConfiguration{service_id}'
                    
                    # Get number of associated devices
                    result = self.fc.call_action(service_name, 'GetTotalAssociations')
                    total = result.get('NewTotalAssociations', 0)
                    
                    # Get BSSID (MAC address of this access point)
                    bssid_result = self.fc.call_action(service_name, 'GetInfo')
                    ap_mac = bssid_result.get('NewBSSID', '')
                    
                    print(f"{service_name}: {total} devices on AP {ap_mac}")
                    
                    # Get each associated device
                    for i in range(total):
                        try:
                            device_info = self.fc.call_action(
                                service_name,
                                'GetGenericAssociatedDeviceInfo',
                                NewAssociatedDeviceIndex=i
                            )
                            
                            device_mac = device_info.get('NewAssociatedDeviceMACAddress', '')
                            if device_mac:
                                wlan_devices.append({
                                    'device_mac': device_mac,
                                    'ap_mac': ap_mac,
                                    'service': service_name,
                                    'ip': device_info.get('NewAssociatedDeviceIPAddress', ''),
                                    'signal_strength': device_info.get('NewX_AVM-DE_SignalStrength', 0),
                                    'speed': device_info.get('NewX_AVM-DE_Speed', 0),
                                })
                        except Exception:
                            continue
                            
                except Exception:
                    # Service might not exist, continue to next
                    continue
            
            print(f"Total WLAN devices collected: {len(wlan_devices)}")
                    
        except Exception as e:
            print(f"Error getting WLAN devices: {e}")
            
        return wlan_devices

