# Implementation Guide: Fritz!Box Monitoring

## 🔧 Wie Traffic-Monitoring funktioniert

### Problem: GetSpecificHostEntry liefert keine Traffic-Daten

Die Fritz!Box TR-064 API hat eine **Hardware-Limitation**:

```python
# ❌ Funktioniert NICHT (liefert immer 0):
result = fc.call_action('Hosts1', 'GetSpecificHostEntry', NewMACAddress=mac)
rx_bytes = result.get('NewX_AVM-DE_RxBytes', 0)  # → Immer 0
tx_bytes = result.get('NewX_AVM-DE_TxBytes', 0)  # → Immer 0
```

**Grund:** Die Fritz!Box Hardware trackt keine individuellen Traffic-Counter pro Gerät.

---

## ✅ Implementierte Lösung

### 1. **Mesh Link-Speeds** (für Repeater/Powerline)

Die Mesh-Topologie enthält **Echtzeit-Datenraten** zwischen Knoten:

```python
mesh_topology = hosts.get_mesh_topology()

for node in mesh_topology['nodes']:
    for interface in node['node_interfaces']:
        for link in interface['node_links']:
            rx_kbps = link['cur_data_rate_rx']  # Download in kbps
            tx_kbps = link['cur_data_rate_tx']  # Upload in kbps
```

**Speicherung in Discovery:**
```python
# Aggregiere alle Links pro Node
node_mac_to_link_speeds = {}

for link in node_links:
    cur_rx = link.get('cur_data_rate_rx', 0)
    cur_tx = link.get('cur_data_rate_tx', 0)
    
    node_mac_to_link_speeds[mac]['rx_kbps'] += cur_rx
    node_mac_to_link_speeds[mac]['tx_kbps'] += cur_tx

# In Node.extra speichern
node.extra = {
    'link_rx_kbps': link_speeds['rx_kbps'],
    'link_tx_kbps': link_speeds['tx_kbps']
}
```

**Export in Prometheus:**
```python
self.node_link_rx_kbps.labels(
    name=node.name,
    mac=node.mac,
    type=node_type
).set(node.extra.get('link_rx_kbps', 0))
```

**Resultat:**
```
fritz_node_link_rx_kbps{name="Repeater-05EC", type="repeater"} 2331800  # 2.3 Gbps
fritz_node_link_tx_kbps{name="Repeater-05EC", type="repeater"} 1814700  # 1.8 Gbps
```

---

### 2. **WLAN Device Statistics** (für WiFi-Geräte)

**API-Call:**
```python
def get_wlan_devices(self):
    wlan_devices = []
    for service_id in range(1, 5):  # WLANConfiguration1-4
        service_name = f'WLANConfiguration{service_id}'
        
        # Get BSSID (AP MAC)
        bssid_result = self.fc.call_action(service_name, 'GetInfo')
        ap_mac = bssid_result.get('NewBSSID', '')
        
        # Get associated devices
        total = self.fc.call_action(service_name, 'GetTotalAssociations')
        
        for i in range(total['NewTotalAssociations']):
            device_info = self.fc.call_action(
                service_name,
                'GetGenericAssociatedDeviceInfo',
                NewAssociatedDeviceIndex=i
            )
            
            wlan_devices.append({
                'device_mac': device_info['NewAssociatedDeviceMACAddress'],
                'ap_mac': ap_mac,  # Zeigt, an welchem AP das Gerät hängt!
                'signal_strength': device_info.get('NewX_AVM-DE_SignalStrength', 0),
                'speed': device_info.get('NewX_AVM-DE_Speed', 0),
                'ip': device_info.get('NewAssociatedDeviceIPAddress', '')
            })
    
    return wlan_devices
```

**Speicherung in Discovery:**
```python
device_mac_to_wlan_stats = {}

for wlan_dev in wlan_devices:
    mac = wlan_dev['device_mac'].upper()
    device_mac_to_wlan_stats[mac] = {
        'signal_strength': wlan_dev.get('signal_strength', 0),
        'speed': wlan_dev.get('speed', 0)
    }

# In Device.extra speichern
device.extra = {
    'signal_strength': wlan_stats['signal_strength'],
    'speed': wlan_stats['speed']
}
```

**Export in Prometheus:**
```python
if device.interface_type == "802.11":  # WiFi device
    signal = device.extra.get('signal_strength', 0)
    speed = device.extra.get('speed', 0)
    
    self.device_wlan_signal_strength.labels(...).set(signal)
    self.device_wlan_speed_mbps.labels(...).set(speed)
```

**Resultat:**
```
fritz_device_wlan_signal_strength{mac="28:24:C9:DE:B5:97", name="Android"} 95.0
fritz_device_wlan_speed_mbps{mac="28:24:C9:DE:B5:97", name="Android"} 866.0
```

---

### 3. **WAN Traffic** (für Router Gesamt-Traffic)

**API-Call:**
```python
def get_wan_stats(self):
    current_rates = self.status.transmission_rate  # (downstream, upstream) bytes/sec
    
    return {
        'bytes_sent': self.status.bytes_sent,
        'bytes_received': self.status.bytes_received,
        'current_download_rate': current_rates[0],  # bytes/sec
        'current_upload_rate': current_rates[1],    # bytes/sec
        'max_byte_rate_up': self.status.max_byte_rate[1],
        'max_byte_rate_down': self.status.max_byte_rate[0],
        'uptime': self.status.device_uptime,
        'connection_uptime': self.status.connection_uptime,
        'is_connected': self.status.is_connected
    }
```

**Resultat:**
```
fritz_router_current_bytes_received_rate 125000000  # 125 MB/s = 1 Gbit/s
fritz_router_current_bytes_sent_rate     15625000   # 15.6 MB/s = 125 Mbit/s
```

---

## 📊 Metriken-Übersicht

### Vollständige Liste exportierter Metriken:

```python
# Router WAN Metrics
fritz_router_bytes_received_total              # Counter
fritz_router_bytes_sent_total                  # Counter
fritz_router_current_bytes_received_rate       # Gauge (Echtzeit!)
fritz_router_current_bytes_sent_rate           # Gauge (Echtzeit!)
fritz_router_max_byte_rate_down                # Gauge
fritz_router_max_byte_rate_up                  # Gauge
fritz_router_uptime_seconds                    # Gauge
fritz_router_connection_uptime_seconds         # Gauge
fritz_router_is_connected                      # Gauge (1/0)
fritz_router_external_ip{ip}                   # Info Metric
fritz_router_dsl_downstream_attenuation        # Gauge (dB)
fritz_router_dsl_upstream_attenuation          # Gauge (dB)
fritz_router_dsl_downstream_noise_margin       # Gauge (dB)
fritz_router_dsl_upstream_noise_margin         # Gauge (dB)
fritz_router_cpu_temperature_celsius{cpu}      # Gauge

# Device Count Metrics
fritz_total_devices                            # Gauge
fritz_online_devices                           # Gauge
fritz_offline_devices                          # Gauge

# WLAN Interface Metrics
fritz_wlan_packets_sent_total                  # Gauge
fritz_wlan_packets_received_total              # Gauge

# Mesh Node Metrics
fritz_node_up{name, mac, type}                              # Gauge (1/0)
fritz_node_info{name, mac, type, model, ip, parent_name}    # Info Metric
fritz_node_link_rx_kbps{name, mac, type}                    # Gauge (Echtzeit!)
fritz_node_link_tx_kbps{name, mac, type}                    # Gauge (Echtzeit!)
fritz_node_rx_bytes_total{name, mac, type}                  # Gauge (aggregiert)
fritz_node_tx_bytes_total{name, mac, type}                  # Gauge (aggregiert)
fritz_node_parent{name, mac, parent_name, parent_mac}       # Info Metric

# Per-Node Device Counts
fritz_repeater_connected_devices{name, mac}     # Gauge
fritz_powerline_connected_devices{name, mac}    # Gauge

# Per-Device Metrics
fritz_device_up{mac, name, ip, node, node_mac, interface, repeater, powerline}  # Gauge (1/0)
fritz_device_rx_bytes_total{...}                # Gauge (meist 0 wegen HW-Limit)
fritz_device_tx_bytes_total{...}                # Gauge (meist 0 wegen HW-Limit)
fritz_device_wlan_signal_strength{mac, name, ip, node, node_mac}  # Gauge (0-100%)
fritz_device_wlan_speed_mbps{mac, name, ip, node, node_mac}       # Gauge (Mbps)

# Log Metrics
fritz_log_total                                # Gauge
fritz_log_by_severity{severity}                # Gauge
fritz_log_by_category{category}                # Gauge
fritz_log_by_source{source}                    # Gauge
```

---

## 🔍 Device-to-AP Assignment

**Wie wird ermittelt, welches Gerät an welchem Access Point hängt?**

### Mapping-Strategie (Priorität von oben nach unten):

```python
# 1. BEST: WLAN Association (für WiFi-Geräte)
if mac_upper in device_mac_to_ap_mac:
    ap_mac = device_mac_to_ap_mac[mac_upper]
    connected_node = ap_mac_to_mesh_name[ap_mac]
    mapping_source = "wlan"

# 2. GOOD: Mesh Topology IP Mapping (für LAN-Geräte)
elif ip in device_ip_to_node_uid:
    node_uid = device_ip_to_node_uid[ip]
    connected_node = uid_to_unique_name[node_uid]
    mapping_source = "mesh_ip"

# 3. FALLBACK: Static IP Mapping (manuell konfiguriert)
elif ip in static_ip_to_repeater:
    connected_node = static_ip_to_repeater[ip]
    mapping_source = "static_ip_override"

# 4. DEFAULT: Router
else:
    connected_node = "fritz.box"
    mapping_source = "default_router"
```

**Beispiel WLAN-Mapping:**
```python
# WLAN-Device → AP MAC → Mesh Node Name → Unique Name
'28:24:C9:DE:B5:97'        # Android Phone MAC
  → '12:72:74:67:BC:CF'    # Powerline AP BSSID
    → 'Powerline 1260E'    # Mesh Topology Name
      → 'Powerline-BCCF'   # Standardized Unique Name
```

---

## 🎨 Code-Struktur

### Dateiübersicht:

```
src/fritz_monitoring/
├── avm/
│   ├── connection.py          # Fritz!Box API Wrapper
│   │   ├── get_wlan_devices()     # WLAN Associations
│   │   ├── get_mesh_info()        # Mesh Topology
│   │   ├── get_wan_stats()        # WAN Statistics
│   │   └── get_device_stats()     # Device Traffic (liefert 0)
│   │
│   ├── discovery.py           # Node & Device Discovery
│   │   ├── discover()             # Main Discovery Logic
│   │   ├── device_mac_to_ap_mac   # WLAN → AP Mapping
│   │   ├── device_mac_to_wlan_stats  # Signal/Speed Storage
│   │   ├── node_mac_to_link_speeds   # Link Speed Aggregation
│   │   └── mesh_name_to_unique_name  # Name Standardization
│   │
│   └── models.py              # Data Models (Node, Device)
│
└── exporter/
    └── prometheus_exporter.py # Metrics Export
        ├── update_from_snapshot()  # Update all metrics
        ├── node_link_rx_kbps       # Link Speed Metrics
        └── device_wlan_*           # WLAN Device Metrics
```

---

## 🐛 Debugging

### Häufige Probleme:

**1. Link-Speeds zeigen 0:**
```bash
# Prüfe ob Mesh-Topologie verfügbar ist:
docker exec <container> python -c "
from fritzconnection.lib.fritzhosts import FritzHosts
fc = FritzHosts(address='192.168.178.1', user='...', password='...')
mesh = fc.get_mesh_topology()
print(f\"Nodes: {len(mesh.get('nodes', []))}\")
"
```

**Fix:** Link-Speeds müssen während **Mesh-Node-Creation** gespeichert werden, nicht nur bei Host-Updates.

**2. WLAN Signal/Speed zeigen nichts:**
```bash
# Prüfe WLAN-Associations:
docker exec <container> python -c "
from fritz_monitoring.avm.connection import FritzClient
from fritz_monitoring.config import Settings
client = FritzClient(Settings())
wlan = client.get_wlan_devices()
print(f\"WLAN Devices: {len(wlan)}\")
for dev in wlan[:3]:
    print(f\"  {dev['device_mac']}: Signal={dev.get('signal_strength', 0)}, Speed={dev.get('speed', 0)}\")
"
```

**Fix:** Sicherstellen, dass `device_mac_to_wlan_stats` gefüllt wird und in `Device.extra` übertragen wird.

**3. Devices zeigen falschen Node:**
```bash
# Check Mapping-Source:
curl -s http://localhost:8000/metrics | grep 'fritz_device_up.*Android'
```

Prüfe `device.extra['mapping']` um zu sehen, welcher Mapping-Mechanismus verwendet wurde.

---

## 📈 Performance

### Typische Discovery-Zeiten:

```
get_wlan_devices()    → 2-5 Sekunden
get_mesh_topology()   → 1-3 Sekunden
get_all_hosts()       → 3-8 Sekunden (85 Hosts)
Total Discovery       → 10-15 Sekunden
```

### Optimierungen:

1. **Caching:** Discovery läuft alle 60 Sekunden (konfigurierbar)
2. **Parallel Requests:** Mesh + WLAN + Hosts parallel abrufen (TODO)
3. **Incremental Updates:** Nur geänderte Devices updaten (TODO)

---

## 🚀 Deployment

### Docker-Compose:

```yaml
fritz_exporter:
  build:
    context: .
    dockerfile: docker/Dockerfile.exporter
  environment:
    - FRITZ_HOST=192.168.178.1
    - FRITZ_USERNAME=admin
    - FRITZ_PASSWORD=secret
  ports:
    - "8000:8000"
  restart: unless-stopped
```

### Prometheus Scrape Config:

```yaml
scrape_configs:
  - job_name: 'fritz_exporter'
    scrape_interval: 60s
    static_configs:
      - targets: ['fritz_exporter:8000']
```

---

## 📚 Weitere Informationen

- [Fritz!Box API Capabilities](./FRITZ_BOX_API_CAPABILITIES.md)
- [Grafana Dashboard Examples](../config/grafana/provisioning/dashboards_files/)
- [fritzconnection Library](https://github.com/kbr/fritzconnection)
