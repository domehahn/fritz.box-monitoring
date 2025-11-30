```
fritz.box-monitoring/
│
├── 📄 README.md                          # Projekt Übersicht und Features
├── 📄 QUICKSTART.md                      # Schnell-Anleitung für Anfänger
├── 📄 Makefile                           # Convenience Commands (make help)
├── 📄 docker-compose.yml                 # Docker Stack Definition
├── 📄 pyproject.toml                     # Poetry Abhängigkeiten & Config
├── 📄 .gitignore                         # Git Ignore Konfiguration
├── 📄 .pre-commit-config.yaml            # Pre-commit Hooks
├── 📄 .env.example                       # Environment Template
│
├── 📁 src/fritz_monitoring/              # ⭐ Hauptquellcode
│   ├── __init__.py                       # Package Init
│   ├── config.py                         # Pydantic Settings & Config
│   ├── logger.py                         # Loguru Logger Setup
│   ├── collector.py                      # Fritz!Box Datenerfassung (async)
│   ├── exporter.py                       # Prometheus Metriken Exporter
│   ├── server.py                         # aiohttp HTTP Server
│   └── cli.py                            # Click CLI Entry Point
│
├── 📁 tests/                             # 🧪 Unit Tests
│   ├── conftest.py                       # pytest Konfiguration
│   ├── test_config.py                    # Config Tests
│   ├── test_collector.py                 # Collector Tests
│   └── test_exporter.py                  # Exporter Tests
│
├── 📁 config/                            # ⚙️ Service Konfigurationen
│   ├── prometheus.yml                    # Prometheus Scrape Config
│   ├── alertmanager.yml                  # Alertmanager Konfiguration
│   └── grafana/
│       ├── provisioning/
│       │   ├── datasources.yml           # Grafana Datasource (Prometheus)
│       │   └── dashboards.yml            # Grafana Dashboard Provisioning
│       └── dashboards/
│           └── fritz-dashboard.json      # Haupt-Dashboard JSON
│
├── 📁 docker/                            # 🐳 Docker Konfiguration
│   └── Dockerfile                        # Python Exporter Image
│
├── 📁 .github/                           # 🔄 CI/CD
│   └── workflows/
│       └── ci.yml                        # GitHub Actions Pipeline
│
└── 📁 docs/                              # 📚 Dokumentation
    ├── architecture.md                   # Systemarchitektur Tiefgang
    └── troubleshooting.md                # Fehler-Lösungsguide
```

## 🎯 Schnelle Navigationshilfe

### 🚀 Für Anfänger
1. **README.md** - Was ist dieses Projekt?
2. **QUICKSTART.md** - Wie starte ich es?
3. **make help** - Alle Befehle

### 👨‍💻 Für Entwickler
1. **src/fritz_monitoring/** - Hauptlogik
2. **tests/** - Unit Tests
3. **docker-compose.yml** - Service Definition

### 🔧 Für DevOps/Sysadmin
1. **docker-compose.yml** - Docker Stack
2. **.env.example** - Environment Setup
3. **config/** - Service Konfigurationen

### 📖 Für Deep Dive
1. **docs/architecture.md** - Design & Technologie Stack
2. **docs/troubleshooting.md** - Fehlerbehandlung
3. **pyproject.toml** - Abhängigkeiten & Scripts

## 📊 Services & Ports

| Service | Port | URL | Rolle |
|---------|------|-----|-------|
| **Fritz Exporter** | 8000 | http://localhost:8000/metrics | Python Agent |
| **Prometheus** | 9090 | http://localhost:9090 | Metrics DB |
| **Grafana** | 3000 | http://localhost:3000 | Dashboard |
| **InfluxDB** | 8086 | http://localhost:8086 | Time-Series DB |
| **Node Exporter** | 9100 | http://localhost:9100 | System Metrics |
| **Alertmanager** | 9093 | http://localhost:9093 | Alert Management |

## 🛠️ Wichtige Commands

```bash
# Projekt starten
make setup      # Alles vorbereiten
make start      # Services starten
make up         # oder: docker-compose up -d

# Entwicklung
make lint       # Code-Qualität prüfen
make test       # Tests ausführen
make format     # Code formatieren
make dev        # Im Debug-Modus laufen

# Management
make logs       # Logs anschauen
make restart    # Services neu starten
make health     # Health Check aller Services
make metrics    # Fritz!Box Metriken anzeigen

# Cleanup
make clean      # Alles zurücksetzen

# Hilfe
make help       # Alle verfügbaren Commands
```

## 🔐 Wichtig für Production

- [ ] `.env` erstellen mit echten Credentials
- [ ] Grafana default Passwort ändern
- [ ] InfluxDB default Passwort ändern
- [ ] Reverse Proxy + SSL/TLS einrichten
- [ ] Persistente Volumes verwenden
- [ ] Firewall Regeln setzen
- [ ] Monitoring für die Monitoring-Stack

## 📦 Python Abhängigkeiten (poetry)

| Paket | Version | Zweck |
|-------|---------|-------|
| fritzconnection | ^1.14 | Fritz!Box API Access |
| prometheus-client | ^0.19 | Prometheus Export |
| pydantic | ^2.5 | Settings Validation |
| aiohttp | ^3.9 | Async HTTP Server |
| loguru | ^0.7 | Logging |
| click | ^8.1 | CLI Framework |

## 🐳 Docker Images

| Image | Version | Rolle |
|-------|---------|-------|
| prom/prometheus | latest | Metrics Storage |
| grafana/grafana | latest | Visualization |
| influxdb | 2.7 | Time-Series DB |
| prom/node-exporter | latest | System Metrics |
| prom/alertmanager | latest | Alert Management |
| python | 3.11-slim | Base für Exporter |

## 🎓 Lernpfad

1. **Grundlagen** (15 min)
   - QUICKSTART.md lesen
   - `make start` ausführen
   - Grafana Dashboard öffnen

2. **Funktionsweise** (30 min)
   - docs/architecture.md lesen
   - Quellcode anschauen (src/fritz_monitoring/)
   - Services in logs beobachten

3. **Anpassung** (1-2h)
   - Neue Metriken hinzufügen (collector.py)
   - Dashboard Panels bearbeiten (Grafana)
   - Alerts konfigurieren (alertmanager.yml)

4. **Production** (2-4h)
   - SSL/TLS Setup
   - Reverse Proxy Konfiguration
   - Backup & Restoration
   - Monitoring der Monitoring-Stack

## 📞 Support

- **Schnelle Probleme**: `docs/troubleshooting.md`
- **Befehle**: `make help`
- **Architektur**: `docs/architecture.md`
- **Logs**: `make logs`
- **Health Check**: `make health`

---

**Letzte Aktualisierung**: 30. November 2025
**Ersteller**: AI Assistant
**Status**: ✅ Production Ready
```
