# Fritz!Box Monitoring System

Ein umfassendes Überwachungssystem für alle Fritz!Box Geräte und das Heimnetzwerk, basierend auf modernen CNCF-Tools.

## 📋 Features

- **Fritz!Box Überwachung**: Automatische Erfassung aller relevanten Metriken
  - WAN-Verbindungsstatus und Geschwindigkeit
  - Verbundene Geräte
  - WLAN-Status
  - Uptime und System-Information

- **Prometheus Integration**: Standard-Metrik-Export für Monitoring
- **Grafana Dashboards**: Vordefinierte Dashboards für sofortige Visualisierung
- **Alerting**: Prometheus Alertmanager für Benachrichtigungen
- **InfluxDB Support**: Optional für erweiterte Zeitreihenverwaltung
- **Containerisiert**: Docker Compose für einfaches Deployment

## 🚀 Quick Start

### Voraussetzungen

- Docker und Docker Compose
- oder: Python 3.11+, Poetry

### Installation mit Docker Compose

1. **Repository klonen**
```bash
git clone <repository-url>
cd fritz.box-monitoring
```

2. **Environment-Variablen setzen**
```bash
cp .env.example .env
# Bearbeite .env mit deinen Fritz!Box Zugangsdaten
```

3. **Stack starten**
```bash
docker-compose up -d
```

4. **Zugriff auf Services**
- Grafana: http://localhost:3000 (admin / admin)
- Prometheus: http://localhost:9090
- Fritz Exporter: http://localhost:8000/metrics
- Alertmanager: http://localhost:9093

## 🔧 Manuelle Installation

### Mit Poetry

```bash
# Installation
poetry install

# Environment konfigurieren
cp .env.example .env
# Bearbeite .env

# Exporter starten
poetry run fritz-monitor run
```

### Docker Image erstellen

```bash
docker build -f docker/Dockerfile -t fritz-exporter:latest .
```

## 📊 Metriken

Der Exporter stellt folgende Prometheus-Metriken zur Verfügung:

| Metrik | Beschreibung |
|--------|-------------|
| `fritzbox_connected` | WAN-Verbindungsstatus (0/1) |
| `fritzbox_downstream_speed_mbs` | Download-Geschwindigkeit in Mbps |
| `fritzbox_upstream_speed_mbs` | Upload-Geschwindigkeit in Mbps |
| `fritzbox_bytes_sent_total` | Gesamt gesendete Bytes |
| `fritzbox_bytes_received_total` | Gesamt empfangene Bytes |
| `fritzbox_connected_devices` | Anzahl verbundener Geräte |
| `fritzbox_wlan_associated_devices` | Anzahl WLAN-Geräte |
| `fritzbox_uptime_seconds` | Fritz!Box Uptime in Sekunden |
| `fritzbox_scrape_duration_seconds` | Dauer des Metric Scraping |
| `fritzbox_scrape_errors_total` | Fehlerrate beim Scraping |

## 🎯 Konfiguration

### Environment-Variablen

```env
# Fritz!Box Verbindung
FRITZ_HOST=192.168.178.1
FRITZ_PORT=49000
FRITZ_USERNAME=dslf
FRITZ_PASSWORD=your_password

# Exporter
EXPORTER_PORT=8000
EXPORTER_HOST=0.0.0.0

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/fritz_monitoring.log

# Collection Intervall
COLLECTION_INTERVAL=60
```

### Prometheus Konfiguration

Die Datei `config/prometheus.yml` konfiguriert:
- Scrape Interval: 60 Sekunden
- Evaluation Interval: 60 Sekunden
- Alertmanager Integration

### Grafana Dashboards

Das Dashboard wird automatisch bereitgestellt. Es zeigt:
- WAN-Verbindungsstatus
- Geschwindigkeitstrends
- Geräte- und WLAN-Statistiken
- Datenverkehr
- Uptime-Informationen

## 🧪 Tests

```bash
# Tests ausführen
poetry run pytest

# Mit Coverage
poetry run pytest --cov=src/fritz_monitoring

# HTML Coverage Report
open htmlcov/index.html
```

## 📝 Code Quality

```bash
# Linting
poetry run ruff check src tests

# Code Formatting
poetry run black src tests

# Type Checking
poetry run mypy src
```

## 🐳 Docker

### Docker Compose Services

- **prometheus**: Time-series database und Metrics Storage
- **grafana**: Visualization und Dashboards
- **influxdb**: Alternative Zeitreihendatenbank (optional)
- **node_exporter**: System-Metriken
- **alertmanager**: Alert Management
- **fritz_exporter**: Custom Fritz!Box Exporter

### Custom Image bauen

```bash
docker build -f docker/Dockerfile -t fritz-exporter:latest .
```

## 🔔 Alerts

Der Alertmanager in `config/alertmanager.yml` kann für verschiedene Notification Channels konfiguriert werden:
- Slack
- Email
- PagerDuty
- Webhooks

## 📚 Dokumentation

- [Architecture](/docs/architecture.md)
- [API Reference](/docs/api.md)
- [Troubleshooting](/docs/troubleshooting.md)

## 🛠 Entwicklung

### Projektstruktur

```
fritz.box-monitoring/
├── src/fritz_monitoring/      # Hauptquellcode
│   ├── collector.py           # Fritz!Box Datenerfassung
│   ├── exporter.py            # Prometheus Exporter
│   ├── config.py              # Konfiguration
│   ├── logger.py              # Logging Setup
│   ├── cli.py                 # CLI Entry Point
│   └── server.py              # HTTP Server
├── tests/                     # Unit Tests
├── config/                    # Konfigurationsdateien
│   ├── prometheus.yml
│   ├── alertmanager.yml
│   └── grafana/
├── docker/                    # Docker Files
└── docs/                      # Dokumentation
```

### Neuer Feature

1. Erstelle einen Branch: `git checkout -b feature/your-feature`
2. Schreibe Tests in `tests/`
3. Implementiere Feature in `src/`
4. Stelle sicher, dass Tests passen: `poetry run pytest`
5. Commit und Push
6. Erstelle einen Pull Request

## 📄 Lizenz

MIT License - siehe [LICENSE](LICENSE) für Details

## 👥 Beitragen

Contributions sind willkommen! Bitte erstelle einen Pull Request mit:
- Ausführliche Beschreibung der Änderungen
- Tests für neue Features
- Aktualisierte Dokumentation

## 🆘 Support

Bei Problemen:
1. Prüfe die [Troubleshooting Guide](/docs/troubleshooting.md)
2. Öffne ein Issue im Repository
3. Kontaktiere den Maintainer

## 🔐 Sicherheit

**WICHTIG**: 
- Speichere nie Passwörter im Repository
- Nutze `.env` für sensitive Daten
- `.env` ist in `.gitignore`
- Wechsel die default Grafana/InfluxDB Passwörter

---

**Made with ❤️ for Heimnetzwerk Monitoring**
