# Quick Start Guide

Schnelle Anleitung zum Starten des Fritz!Box Monitoring Systems.

## 🍎 macOS mit Colima (Empfohlen)

Wenn du Colima statt Docker Desktop nutzt:

### Schritt 0: Colima einrichten
```bash
# Colima installieren
brew install colima

# Automatisches Setup (empfohlen)
make colima-setup

# Oder manuell
./setup-colima.sh --cpu 4 --memory 6 --disk 50
```

**Colima-Befehle:**
```bash
make colima-status    # Status prüfen
make colima-stop      # Beenden (wenn nicht mehr nötig)
make colima-logs      # Logs anschauen
```

Dann weitermachen mit Schritt 1 unten.

---

## 🚀 Schritt 1: Vorbereitung (5 Minuten)

### Schritt 1.1: Repository klonen
```bash
cd ~/dev/workspace
# Repository ist bereits hier
cd fritz.box-monitoring
```

### Schritt 1.2: Docker überprüfen
```bash
# Docker muss laufen
docker --version
docker-compose --version

# Unter macOS: Falls Colima läuft, sollte alles funktionieren
# Wenn nicht: make colima-setup
```

### Schritt 1.3: Environment einrichten
```bash
# .env Datei erstellen
cp .env.example .env

# .env Datei anpassen
nano .env  # oder dein liebster Editor
```

**Wichtige Einstellungen:**
```env
FRITZ_HOST=192.168.178.1       # Deine Fritz!Box IP
FRITZ_PORT=49000               # Standard Port
FRITZ_USERNAME=dslf            # Standard User
FRITZ_PASSWORD=dein_passwort   # Dein Fritz!Box Passwort
```

---

## 🐳 Schritt 2: Mit Docker Compose starten (3 Minuten)

### Schnellstart
```bash
make setup    # Alles vorbereiten
make start    # Services starten
```

### Oder einzeln
```bash```bash
# Images bauen
docker-compose build

# Services starten
docker-compose up -d

# Status prüfen
docker-compose ps
```

**Output sollte so aussehen:**
```
NAME                  STATUS
fritz_prometheus      Up 2 minutes
fritz_grafana         Up 2 minutes
fritz_exporter        Up 2 minutes
fritz_influxdb        Up 2 minutes
fritz_node_exporter   Up 2 minutes
fritz_alertmanager    Up 2 minutes
```

---

## 🌐 Schritt 3: Services öffnen (2 Minuten)

### Grafana - Dashboards & Visualisierung
```
URL: http://localhost:3000
Username: admin
Password: admin
```
- ✅ Login mit admin/admin
- ✅ Dashboard "Fritz!Box Monitoring Dashboard" sollte sichtbar sein
- ✅ Metriken sollten nach 1-2 Minuten erscheinen

### Prometheus - Metriken & Queries
```
URL: http://localhost:9090
```
- ✅ Status → Targets (sollte "fritz-exporter" als "UP" zeigen)
- ✅ Graphs → Metriken abfragen
- ✅ Beispiel Query: `fritzbox_downstream_speed_mbs`

### Fritz Exporter - Raw Metrics
```
URL: http://localhost:8000/metrics
```
- ✅ Raw Prometheus Format
- ✅ Health Check: http://localhost:8000/health

---

## 🔍 Schritt 4: Metriken überprüfen (2 Minuten)

### Alle Fritz!Box Metriken anschauen
```bash
curl http://localhost:8000/metrics | grep fritzbox
```

### Spezifische Metriken überprüfen
```bash
# WAN Connection Status (0=disconnected, 1=connected)
curl http://localhost:8000/metrics | grep "fritzbox_connected "

# Download Speed in Mbps
curl http://localhost:8000/metrics | grep "fritzbox_downstream_speed_mbs"

# Verbundene Geräte
curl http://localhost:8000/metrics | grep "fritzbox_connected_devices"

# WLAN Geräte
curl http://localhost:8000/metrics | grep "fritzbox_wlan_associated_devices"
```

### Mit Live-Watch
```bash
# Terminal-Watch aktivieren (aktualisiert sich alle 5 Sekunden)
watch -n 5 'curl -s http://localhost:8000/metrics | grep fritzbox'

# Oder mit Make
make metrics-watch
```

---

## 📊 Schritt 5: Grafana Dashboard nutzen

### Dashboard öffnen
1. Öffne http://localhost:3000
2. Login mit `admin` / `admin`
3. Suche "Fritz!Box Monitoring Dashboard"

### Dashboard Panels
- **WAN Connection Status**: Grün = verbunden, Rot = getrennt
- **Connection Speed**: Download und Upload Trend
- **Connected Devices**: Anzahl verbundener Netzwerkgeräte
- **WLAN Devices**: Anzahl WLAN-verbundener Geräte
- **Data Transfer**: Gesamt Datenmenge gesendet/empfangen
- **Uptime**: Wie lange Fritz!Box läuft

---

## 🛠️ Häufige Befehle

### Logs anschauen
```bash
# Alle Logs
docker-compose logs

# Nur Exporter
docker-compose logs -f fritz_exporter

# Nur Grafana
docker-compose logs -f grafana

# Letzten 50 Zeilen
docker-compose logs --tail=50
```

### Services neu starten
```bash
# Alles neu starten
make restart

# Oder spezifische Services
docker-compose restart fritz_exporter
docker-compose restart prometheus
docker-compose restart grafana
```

### Aufräumen
```bash
# Logs löschen
docker-compose down

# Mit Volumen (Datenbank, Grafana Settings) löschen
docker-compose down -v

# Alles neu bauen
docker-compose up -d --build
```

---

## ❌ Häufige Probleme

### "fritz_exporter ist DOWN in Prometheus"
```bash
# 1. Logs anschauen
docker-compose logs fritz_exporter

# 2. Health Check
curl http://localhost:8000/health

# 3. Fritz!Box erreichbar?
ping 192.168.178.1
```

### "Keine Metriken in Grafana"
```bash
# 1. Warten Sie 2-3 Minuten (erste Datensammlung)
# 2. Prometheus prüfen: http://localhost:9090
# 3. Exporter Metrics: curl http://localhost:8000/metrics
```

### "Port 3000 bereits in Benutzung"
```bash
# Find process
lsof -i :3000

# Oder in docker-compose.yml Port ändern
# ports:
#   - "3001:3000"
```

---

## 📚 Weitere Ressourcen

### Lokale Dokumentation
```bash
# Architektur verstehen
open docs/architecture.md

# Troubleshooting
open docs/troubleshooting.md

# Weitere Commands
make help
```

### Offizielle Dokumentationen
- [Prometheus Docs](https://prometheus.io/docs/)
- [Grafana Docs](https://grafana.com/docs/)
- [fritzconnection Docs](https://fritzconnection.readthedocs.io/)

---

## ✅ Checkliste - Alles funktioniert wenn:

- [ ] `docker-compose ps` zeigt alle 6 Services als "Up"
- [ ] Grafana lädt ohne Fehler: http://localhost:3000
- [ ] Dashboard hat Metriken (nicht leer)
- [ ] `curl http://localhost:8000/metrics` zeigt fritzbox_* Metriken
- [ ] Prometheus zeigt fritz-exporter als "UP"
- [ ] Logs haben keine kritischen Fehler

---

## 🎯 Nächste Schritte

1. **Customize Dashboard**
   - Grafana: Panels bearbeiten, neue hinzufügen
   - Farben, Schwellenwerte anpassen

2. **Alerts einrichten**
   - Alertmanager in alertmanager.yml konfigurieren
   - Slack/Email Notifications

3. **Produktives Deployment**
   - Auf echtem Server deployen
   - Reverse Proxy einrichten
   - SSL/TLS Zertifikat

4. **Erweiterte Überwachung**
   - Node Exporter Metriken
   - Custom Dashboards
   - InfluxDB für längere Retention

---

**Fertig! Dein Fritz!Box Monitoring System läuft! 🎉**

Bei Fragen siehe `docs/troubleshooting.md`
