# Architektur

## System-Übersicht

```
┌─────────────────────────────────────────────────────────────┐
│                     Fritz!Box (192.168.178.1)                │
│  - WAN Connection Status      - Connected Devices            │
│  - Speed Information          - WLAN Status                  │
│  - Data Transfer              - System Info                  │
└─────────────────┬───────────────────────────────────────────┘
                  │ fritzconnection lib
                  ▼
┌─────────────────────────────────────────────────────────────┐
│         Fritz!Box Collector (Python/Async)                  │
│  - Async Data Collection                                    │
│  - Error Handling & Retry Logic                            │
│  - Periodic Polling (60s interval)                         │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│         Prometheus Exporter (HTTP Server)                   │
│  - /metrics endpoint → Prometheus Text Format              │
│  - /health endpoint → Health Check                         │
│  - Metric Types: Gauge, Counter, Histogram                │
└─────────────────┬───────────────────────────────────────────┘
                  │ HTTP (port 8000)
    ┌─────────────┴────────────────┐
    │                              │
    ▼                              ▼
┌──────────────┐         ┌──────────────────┐
│ Prometheus   │         │  Alert Manager   │
│ (port 9090)  │         │  (port 9093)     │
└──────┬───────┘         └──────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│         Grafana (port 3000)              │
│  - Dashboard Visualization              │
│  - Real-time Monitoring                 │
│  - Alert Integration                    │
└─────────────────────────────────────────┘
```

## Komponenten

### 1. **Fritz!Box Collector** (`collector.py`)
- **Sprache**: Python 3.11+ (async/await)
- **Bibliothek**: fritzconnection
- **Funktion**: Periodische Datenerfassung von der Fritz!Box
- **Metriken**:
  - WAN Connection Status
  - Download/Upload Speed
  - Connected Devices
  - WLAN Status
  - System Information
  - Data Transfer Statistics

### 2. **Prometheus Exporter** (`exporter.py`)
- **Standard**: Prometheus Text Format
- **Metriken-Typen**:
  - **Gauge**: Downloadspeed, Uploadspeed, Connected Status
  - **Counter**: Bytes Sent/Received, Scrape Errors
  - **Histogram**: Scrape Duration
- **Endpoint**: `http://localhost:8000/metrics`

### 3. **HTTP Server** (`server.py`)
- **Framework**: aiohttp (Async)
- **Endpoints**:
  - `GET /metrics` - Prometheus Metriken
  - `GET /health` - Health Check
- **Port**: 8000 (konfigurierbar)

### 4. **Prometheus**
- **Rolle**: Metrik Storage & Zeitreihen-DB
- **Port**: 9090
- **Features**:
  - Automatic Scraping von Exporter
  - Time-Series Data
  - Query Language (PromQL)
  - Built-in Alerting

### 5. **Grafana**
- **Rolle**: Visualization & Dashboarding
- **Port**: 3000
- **Features**:
  - Grafana Dashboards
  - Alert Notification
  - Multi-Source Support
  - User Management

### 6. **Alertmanager**
- **Rolle**: Alert Management & Routing
- **Port**: 9093
- **Features**:
  - Alert Grouping
  - Notification Routing
  - Slack/Email/PagerDuty Integration

### 7. **Node Exporter** (Optional)
- **Rolle**: System Metrics (CPU, Memory, Disk)
- **Port**: 9100
- **Ergänzung**: Gesamt-Systemüberwachung

## Datenfluss

```
1. Fritz!Box Collector scannt die Fritz!Box alle 60 Sekunden
   └─ Nutzt fritzconnection Library für UPnP API
   └─ Sammelt Verbindungsstatus, Geschwindigkeit, Geräte

2. Metriken werden im Memory gepuffert
   └─ Async Processing für schnelle Erfassung
   └─ Error Handling bei Verbindungsausfällen

3. HTTP Server stellt /metrics Endpoint zur Verfügung
   └─ Konvertiert Metriken zu Prometheus Format
   └─ Komprimierung und Caching

4. Prometheus scraped alle 60 Sekunden
   └─ Konfiguriert in config/prometheus.yml
   └─ Speichert Metriken in TSDB
   └─ Evaluiert Alert Rules

5. Grafana liest aus Prometheus
   └─ Visualisiert Daten in Dashboards
   └─ Zeigt Real-time Trends
   └─ Unterstützt Alerting

6. Alertmanager empfängt Alerts von Prometheus
   └─ Routet zu verschiedenen Kanälen
   └─ Gruppiert ähnliche Alerts
```

## Teknologische Stack (CNCF)

| Komponente | Kategorie | Grund |
|-----------|-----------|-------|
| **Prometheus** | Metrics & Observability | De-facto Standard für Cloud-Native Monitoring |
| **Grafana** | Visualization | Universale Dashboarding Lösung |
| **Docker/Compose** | Container | Vereinfachte Deployment & Orchestration |

## Deployment-Optionen

### Option 1: Docker Compose (Lokal)
```bash
docker-compose up -d
```
- Einfachste Lösung für lokale Entwicklung
- Alle Services mit einem Befehl
- Vollständige Isolation

### Option 2: Kubernetes (Zukunft)
```yaml
# Würde später mit Helm Charts deploybar sein
kind: Deployment
metadata:
  name: fritz-exporter
```

### Option 3: Bare Metal
```bash
poetry install
poetry run fritz-monitor run
```
- Für Direct Server Deployment
- Minimale Overhead
- Weniger Abhängigkeiten

## Konfigurationsmanagement

```
.env
├── Fritz!Box Credentials
├── Exporter Settings
├── Logging Configuration
└── Collection Intervals

config/
├── prometheus.yml (Scrape Config)
├── alertmanager.yml (Alert Routing)
└── grafana/
    ├── provisioning/
    │   ├── datasources.yml
    │   └── dashboards.yml
    └── dashboards/
        └── fritz-dashboard.json
```

## Scalability & Performance

### Metriken-Sammlung
- **Sampling Rate**: 60 Sekunden (konfigurierbar)
- **Async Processing**: Non-blocking I/O
- **Memory Usage**: ~50MB base
- **CPU Usage**: <5% average

### Storage
- **Prometheus Default**: 15 days retention
- **InfluxDB Option**: Unbegrenzt (mit Compression)
- **Disk Space**: ~1GB pro Woche

### Skalierungsmöglichkeiten
1. **Multi-Box**: Multiple Fritz!Boxes via separate exporters
2. **Scrape Interval**: Erhöhen für weniger Last
3. **Remote Storage**: Prometheus Remote Storage API
4. **InfluxDB**: Für längere Retention

## Fehlerbehandlung & Resilience

```python
# Retry-Logik für Fritz!Box Verbindung
async def collect_metrics(self):
    try:
        await self.connect()  # Reconnect if needed
        return await self._collect_all()
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        self.exporter.scrape_errors.inc()
        # Metrics bleiben gültig vom letzten erfolgreichen Scrape
```

## Security Considerations

1. **Credentials Management**
   - `.env` für Passwörter
   - Nicht im Repository
   - Docker Secrets für Production

2. **Network Isolation**
   - Docker Network für Service-to-Service
   - Keine externe Exposition (nur Exporter Port)
   - Optional: Reverse Proxy mit Auth

3. **Logging**
   - Sensitive Daten werden nicht geloggt
   - Audit Logs für Admin-Actions
   - Structured Logging mit loguru

---

**Letzte Aktualisierung**: 30. November 2025
