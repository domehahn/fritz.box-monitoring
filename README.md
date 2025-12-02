# Fritz!Box Mesh Network Monitoring

Vollständig **dynamisches** Monitoring-System für Fritz!Box Mesh-Netzwerke mit automatischer Geräte-Erkennung.

## 🚀 Features

- **✨ Automatische Mesh-Erkennung**: Keine manuelle Konfiguration für neue Repeater/Powerline-Adapter nötig
- **🔄 IP-Änderungen werden automatisch erkannt**: Keine Container-Neustarts erforderlich
- **🌐 Echzeit-Netzwerk-Topologie**: Übersicht über alle Mesh-Knoten und Verbindungen
- **📱 Client-Tracking**: Verbindungs-/Trennungs-Events mit Zeitstempeln
- **📋 Event-Logging**: Detaillierte Logs für alle Netzwerk-Ereignisse
- **📊 Prometheus-Metriken**: Monitoring für alle Geräte ohne manuelle Konfiguration

## Quickstart

```bash
# .env Datei erstellen
cp .env.example .env

# Zugangsdaten in .env eintragen
nano .env

# Stack starten
docker-compose up -d
```

## 🏗️ Architektur (Dynamisch!)

Das System besteht aus **nur 7 Containern**:

1. **fritz_exporter**: Haupt-Exporter für Fritz!Box Router
2. **mesh_discovery**: 🎯 Automatische Mesh-Topologie-Erkennung
3. **prometheus**: Metriken-Sammlung mit dynamischen Targets
4. **loki**: Log-Aggregation
5. **promtail**: Log-Sammler
6. **log_pusher**: Event-Log-Pusher
7. **grafana**: Visualisierung & Dashboards

### Wie funktioniert die automatische Erkennung?

1. **Mesh Discovery Service** fragt alle 5 Minuten die Fritz!Box Mesh-Topologie ab
2. Generiert automatisch Prometheus-Targets für alle gefundenen Geräte
3. Schreibt Targets in `/prometheus/targets/mesh-targets.json`
4. **Prometheus** lädt die Targets automatisch alle 60 Sekunden neu
5. Alle Metriken werden **ohne manuelle Konfiguration** gesammelt

**⚡ Wichtig**: Keine Docker-Container-Neustarts nötig bei Netzwerk-Änderungen!

## Produktivbetrieb & Setup

1. Trage deine Fritz!Box-Zugangsdaten in `.env` ein.
2. Starte den Stack:
   ```bash
   docker compose up --build -d
   ```
3. Dienste erreichbar:
   - Exporter: [http://localhost:8000/metrics](http://localhost:8000/metrics)
   - Prometheus: [http://localhost:9090](http://localhost:9090)
   - Grafana: [http://localhost:3000](http://localhost:3000) (admin/admin)
   - Loki: [http://localhost:3100](http://localhost:3100)

### Fritz!Box Logging-Weiterleitung
- In der Fritz!Box unter "System > Ereignisse > Push-Service > Einstellungen" → "Remote Logging" aktivieren.
- Ziel-IP: Docker-Host, Port: 1514 (UDP)

### Dashboards
- **Home Overview**: Wird automatisch provisioniert
- **Panels**:
  - 🌐 Mesh-Netzwerk Topologie
  - 📊 Traffic-Übersicht
  - 🟢 Online Geräte
  - 🔴 Offline Geräte
  - 🔄 Connection Event Log
  - 🕒 Timeline

## 🔄 Geräte hinzufügen/entfernen

**Das ist der Clou**: Du musst **NICHTS** tun!

- ✅ Neuer Repeater gekauft? → Einfach in Fritz!Box Mesh integrieren, fertig!
- ✅ IP-Adresse geändert? → Wird automatisch erkannt (max. 5 Min.)
- ✅ Gerät ausgetauscht? → Automatisch im Dashboard sichtbar
- ✅ Powerline-Adapter entfernt? → Verschwindet automatisch aus dem Monitoring

Das System erkennt **alle Änderungen automatisch**.

## 🔧 Konfiguration

### Discovery-Intervall ändern

In `docker-compose.yml`:
```yaml
mesh_discovery:
  environment:
    - DISCOVERY_INTERVAL=300  # Sekunden (Standard: 5 Minuten)
```

### Prometheus Reload-Intervall

In `config/prometheus.yml`:
```yaml
file_sd_configs:
  - files:
      - /prometheus/targets/mesh-targets.json
    refresh_interval: 1m  # Alle 60 Sekunden neu laden
```

Siehe `.env.example` und `src/fritz_monitoring/config.py` für alle Optionen.

## 🐛 Debugging

### Mesh Discovery Service prüfen:
```bash
# Logs anzeigen
docker-compose logs -f mesh_discovery

# Target-Datei prüfen
docker exec $(docker ps -q -f name=mesh_discovery) cat /prometheus/targets/mesh-targets.json
```

### Prometheus Targets anzeigen:
Öffne: `http://localhost:9090/targets`

Dort siehst du:
- **fritz_main**: Haupt-Router (statisch)
- **fritz_mesh_dynamic**: Alle auto-erkannten Mesh-Geräte

### Container-Status:
```bash
docker-compose ps
docker-compose logs -f <service-name>
```

## 📁 Projekt-Struktur

```
fritz.box-monitoring/
├── config/
│   ├── prometheus.yml              # Prometheus mit file_sd_configs
│   ├── loki/                       # Log-Aggregation
│   ├── promtail/                   # Log-Sammler
│   └── grafana/                    # Auto-provisionierte Dashboards
├── docker/
│   ├── Dockerfile.exporter         # Main Exporter
│   ├── Dockerfile.discovery        # 🎯 Mesh Discovery Service
│   └── Dockerfile.log_pusher       # Event Log Pusher
├── src/
│   └── fritz_monitoring/
│       ├── exporter/               # Prometheus Exporter
│       ├── discovery/              # 🎯 Mesh Discovery Logic
│       │   └── mesh_discovery.py   # Automatische Geräte-Erkennung
│       └── utils/                  # Hilfsfunktionen
├── docker-compose.yml              # 7 Container (statt 12!)
└── .env                            # Credentials (nicht in Git!)
```

## 🔐 Sicherheit

- **Nie** `.env` in Git committen (bereits in `.gitignore`)
- Fritz!Box Credentials nur lokal speichern
- Grafana Admin-Passwort nach erstem Login ändern
- Ports nur im lokalen Netzwerk öffnen

## 🆘 Support

Bei Problemen:

1. Logs prüfen: `docker-compose logs -f`
2. Prometheus Targets prüfen: `http://localhost:9090/targets`
3. Mesh Discovery Status: `docker-compose logs mesh_discovery`
4. Container neu starten: `docker-compose restart <service>`

## Lizenz
MIT

