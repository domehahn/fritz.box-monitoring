# Fritz!Box API Capabilities & Monitoring Architecture

## 🎯 Übersicht

Dieses Dokument beschreibt, wie die Fritz!Box TR-064 API genutzt wird, um ein vollständiges Netzwerk-Monitoring ohne zusätzliche Hardware (Service Mesh, Consul, etc.) zu realisieren.

---

## ✅ Was die Fritz!Box API kann

### 1. **Mesh-Topologie auslesen** (`mesh.lua` / `get_mesh_topology()`)

Die Fritz!Box kennt die komplette Netzwerk-Struktur:

```python
mesh_topology = fritzhosts.get_mesh_topology()
```

**Verfügbare Informationen:**
- ✅ Alle Mesh-Knoten (Router, Repeater, Powerline-Adapter)
- ✅ IP-Adressen aller Geräte
- ✅ MAC-Adressen
- ✅ Mesh-Status (online/offline)
- ✅ **Mesh Link-Speeds** (cur_data_rate_rx/tx in kbps)
- ✅ Parent-Child Beziehungen (Hierarchie)

**Beispiel:**
```json
{
  "nodes": [
    {
      "device_name": "FRITZRepeater 6000",
      "device_mac_address": "48:5D:35:A1:05:EC",
      "node_interfaces": [{
        "node_links": [{
          "cur_data_rate_rx": 2331800,  // 2.3 Gbps Download
          "cur_data_rate_tx": 1814700   // 1.8 Gbps Upload
        }]
      }]
    }
  ]
}
```

---

### 2. **WLAN-Assoziationen pro Access Point** (`WLANConfiguration`)

**Verfügbar über:** `GetGenericAssociatedDeviceInfo`

```python
wlan_devices = connection.get_wlan_devices()
```

**Informationen pro WLAN-Gerät:**
- ✅ **BSSID** (MAC des Access Points) → zeigt, an welchem AP das Gerät hängt
- ✅ **Signal Strength** (0-100%)
- ✅ **Connection Speed** (Mbps)
- ✅ IP-Adresse
- ✅ MAC-Adresse

**Praktisch:**
```python
{
  'device_mac': '28:24:C9:DE:B5:97',
  'ap_mac': '12:72:74:67:BC:CF',        # Powerline-BCCF
  'signal_strength': 95,                # 95%
  'speed': 866,                         # 866 Mbps (WiFi 5)
  'ip': '192.168.178.190'
}
```

---

### 3. **WAN-Statistiken** (Router-Traffic)

**Verfügbar über:** `FritzStatus`

```python
wan_stats = status.get_wan_stats()
```

**Informationen:**
- ✅ Total Bytes Sent/Received (kumulativ)
- ✅ **Current Upload/Download Rate** (bytes/sec) - Echtzeit!
- ✅ Max Line Speed (DSL/Cable)
- ✅ Connection Uptime
- ✅ External IP
- ✅ DSL Quality (Attenuation, Noise Margin)
- ✅ CPU Temperature

---

## ⚠️ Was die Fritz!Box API **NICHT** kann

### 1. **Per-Device Traffic Counters** ❌

**Problem:**
```python
result = fc.call_action('Hosts1', 'GetSpecificHostEntry', NewMACAddress=mac)
# Returns: NewX_AVM-DE_RxBytes = 0, NewX_AVM-DE_TxBytes = 0
```

Die Fritz!Box Hardware trackt **keine individuellen Traffic-Zähler** pro Gerät.

**Workaround:**
- Nutze **Mesh Link-Speeds** für Repeater/Powerline (real-time)
- Nutze **WLAN Speed** für Endgeräte (Verbindungsgeschwindigkeit)
- Nutze **WAN-Statistiken** für Gesamt-Traffic

---

### 2. **Deep Packet Inspection** ❌

Die Fritz!Box kann **nicht** erkennen:
- Welche Apps Traffic erzeugen (YouTube, PSN, Netflix)
- Traffic pro Protokoll (HTTP, HTTPS, Gaming)
- Packet-Level Details

**Alternative für DPI:**
- Raspberry Pi mit `tshark` / `nProbe`
- Unifi / pfSense / OpenWRT Router

---

## 🏗️ Implementierte Monitoring-Architektur

### **Data Flow:**

```
┌─────────────┐
│  Fritz!Box  │
│   TR-064    │
│     API     │
└──────┬──────┘
       │
       ├─► get_mesh_topology()  ────► Link-Speeds (kbps)
       ├─► get_wlan_devices()   ────► Signal, Speed, AP-Zuordnung
       ├─► get_wan_stats()      ────► WAN Traffic (Echtzeit)
       └─► get_all_hosts()      ────► Online/Offline Status
       │
       ▼
┌─────────────────┐
│   Discovery     │
│   (Python)      │
└────────┬────────┘
         │
         ▼
┌──────────────────┐
│ Prometheus       │
│ Exporter         │
│ (Port 8000)      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Grafana         │
│  Dashboards      │
└──────────────────┘
```

---

## 📊 Verfügbare Prometheus Metriken

### **Router-Metriken:**
```
fritz_router_bytes_received_total            # WAN Download (total)
fritz_router_bytes_sent_total                # WAN Upload (total)
fritz_router_current_bytes_received_rate     # Download-Rate (bytes/sec)
fritz_router_current_bytes_sent_rate         # Upload-Rate (bytes/sec)
fritz_router_max_byte_rate_down              # Max Line Speed
fritz_router_uptime_seconds                  # Router Uptime
fritz_router_connection_uptime_seconds       # WAN Connection Uptime
fritz_router_cpu_temperature_celsius         # CPU Temp
```

### **Mesh Node Metriken:**
```
fritz_node_up{name, mac, type}               # 1 = online, 0 = offline
fritz_node_info{name, mac, type, model, ip, parent_name}

# Link-Speeds (Real-time!)
fritz_node_link_rx_kbps{name, mac, type}     # Download in kbps
fritz_node_link_tx_kbps{name, mac, type}     # Upload in kbps

# Device Counts
fritz_repeater_connected_devices{name, mac}   # Anzahl Geräte pro Repeater
fritz_powerline_connected_devices{name, mac}  # Anzahl Geräte pro Powerline
```

### **Device Metriken:**
```
fritz_device_up{mac, name, ip, node, repeater, powerline}

# WLAN Statistiken (NEU!)
fritz_device_wlan_signal_strength{mac, name, ip, node, node_mac}  # 0-100%
fritz_device_wlan_speed_mbps{mac, name, ip, node, node_mac}       # Mbps

# Traffic (Hardware-Limitation: meist 0)
fritz_device_rx_bytes_total{...}             # RX Bytes (meist 0)
fritz_device_tx_bytes_total{...}             # TX Bytes (meist 0)
```

---

## 💡 Use Cases

### **1. Traffic-Fresser identifizieren**

**Frage:** "Welches Gerät lädt gerade ein großes Update?"

**Lösung:**
```promql
# Top 5 WiFi-Geräte nach Speed
topk(5, fritz_device_wlan_speed_mbps)
```

**Beispiel-Ausgabe:**
```
PlayStation5         →  866 Mbps  (Download aktiv!)
iPhone_14            →   72 Mbps  (Streaming)
Smart_TV             →    7 Mbps  (Idle)
```

---

### **2. Repeater Traffic überwachen**

**Frage:** "Wie viel Traffic geht durch meinen Repeater im Obergeschoss?"

**Lösung:**
```promql
# Repeater Link-Speed (Download)
fritz_node_link_rx_kbps{name="Repeater-05EC"} / 1000  # Convert to Mbps
```

**Beispiel:**
```
Repeater-05EC  →  2331 Mbps  (WiFi 6 Backhaul)
Repeater-FEE5  →  2645 Mbps  (sehr gut!)
Repeater-E825  →  1072 Mbps  (WiFi 5)
```

---

### **3. WLAN-Qualität überwachen**

**Frage:** "Welche Geräte haben schlechtes WLAN-Signal?"

**Lösung:**
```promql
# Geräte mit Signal < 50%
fritz_device_wlan_signal_strength < 50
```

**Dashboard-Panel:**
- Signal-Strength Gauge (grün > 70%, gelb 50-70%, rot < 50%)
- Heatmap nach Raum/AP

---

### **4. Mesh-Topologie visualisieren**

**Grafana Panel:**
```promql
fritz_node_parent{parent_name!=""}
```

**Darstellung:**
```
fritz.box (Router)
  ├─ Repeater-05EC (OG)     → 2.3 Gbps Link
  ├─ Repeater-FEE5 (Keller)  → 2.6 Gbps Link
  └─ Powerline-2CB0 (EG)     → 1.5 Gbps Link
      └─ 7 Geräte verbunden
```

---

## 🚫 Was wir NICHT brauchen

### **Service Mesh (Istio, Linkerd)** ❌
- **Zweck:** Microservices-Orchestrierung in Kubernetes
- **Problem:** Fritz!Box/Repeater unterstützen kein Service Mesh
- **Fazit:** Völlig unnötig für Heimnetzwerk

### **Consul** ❌
- **Zweck:** Service Registry / KV-Store
- **Problem:** Overkill für statische Netzwerk-Topologie
- **Fazit:** TR-064 API liefert alle Infos

### **Separate Traffic Sniffer** ❌
- **Zweck:** Packet Capture auf jedem AP
- **Problem:** Nicht nötig - Mesh Link-Speeds reichen
- **Fazit:** Nur für DPI nötig (YouTube vs. Netflix)

---

## ✅ Empfohlene Grafana Dashboards

### **1. Overview Dashboard**
- WAN Up/Download Rate (Echtzeit)
- Online Devices Count
- Mesh Nodes Status

### **2. WiFi Quality Dashboard**
- Signal Strength per Device (Gauge)
- Connection Speed per Device (Bar Chart)
- Top 10 Devices by Speed

### **3. Repeater/Powerline Dashboard**
- Link-Speeds per Node (Time Series)
- Connected Devices per Node (Stat)
- Node Hierarchy (Table)

### **4. Device Tracking Dashboard**
- All Devices with IP/MAC/Node/Signal
- Filter by Repeater/Powerline
- Online/Offline Status

---

## 📝 Beispiel: Grafana Query

### **Panel: "Repeater Traffic (Mbps)"**

```promql
fritz_node_link_rx_kbps{type="repeater"} / 1000
```

**Legende:**
```
{name="Repeater-05EC"}  → 2331 Mbps
{name="Repeater-FEE5"}  → 2645 Mbps
{name="Repeater-E825"}  → 1072 Mbps
```

---

## 🎯 Zusammenfassung

| Feature                          | Fritz!Box API | Alternative       |
|----------------------------------|---------------|-------------------|
| Mesh-Topologie                   | ✅ Perfekt     | -                 |
| WLAN AP-Zuordnung                | ✅ Perfekt     | -                 |
| Link-Speeds (Repeater)           | ✅ Perfekt     | -                 |
| WLAN Signal/Speed                | ✅ Perfekt     | -                 |
| WAN Traffic (Router)             | ✅ Perfekt     | -                 |
| Per-Device Traffic               | ❌ Nicht verfügbar | Raspberry Pi DPI  |
| Deep Packet Inspection           | ❌ Nicht verfügbar | tshark, nProbe    |

**Fazit:** Die Fritz!Box TR-064 API liefert **alles**, was für ein professionelles Heimnetzwerk-Monitoring nötig ist - ohne zusätzliche Hardware oder Software.

---

## 📚 Weitere Ressourcen

- [fritzconnection Dokumentation](https://fritzconnection.readthedocs.io/)
- [Fritz!Box TR-064 Protocol](https://avm.de/service/schnittstellen/)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/)
- [Grafana Dashboard Examples](https://grafana.com/grafana/dashboards/)
