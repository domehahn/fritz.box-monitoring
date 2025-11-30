# Troubleshooting Guide

## Häufige Probleme und Lösungen

### Fritz!Box Verbindung

#### ❌ "Connection refused" oder "Connection timeout"

**Problem**: Exporter kann sich nicht mit Fritz!Box verbinden

**Lösungen**:
1. Prüfe Fritz!Box IP-Adresse
```bash
# Test connectivity
ping 192.168.178.1
```

2. Prüfe Port (Standard: 49000)
```bash
# macOS/Linux
nc -zv 192.168.178.1 49000
```

3. Prüfe Credentials in `.env`
```bash
FRITZ_HOST=192.168.178.1
FRITZ_PORT=49000
FRITZ_USERNAME=dslf
FRITZ_PASSWORD=your_password
```

4. Fritz!Box neustarten
```bash
# Via Web Interface: System → Einstellungen → Neustart
```

---

### Docker Compose

#### ❌ "Cannot connect to Docker daemon"

**Problem**: Docker ist nicht laufend oder nicht installiert

**Lösungen**:
1. Docker Desktop starten (macOS/Windows)
2. Docker Daemon starten (Linux)
```bash
sudo systemctl start docker
```

3. Benutzer zu docker-Gruppe hinzufügen (Linux)
```bash
sudo usermod -aG docker $USER
```

---

#### ❌ "Port already in use"

**Problem**: Port wird bereits von anderer Anwendung genutzt

**Lösungen**:
1. Finde Prozess auf Port (z.B. Port 3000)
```bash
# macOS/Linux
lsof -i :3000

# Windows
netstat -ano | findstr :3000
```

2. Entweder Prozess beenden oder Port in docker-compose.yml ändern
```yaml
ports:
  - "3001:3000"  # Externe Port ändern
```

3. Stack neu starten
```bash
docker-compose restart
```

---

#### ❌ "Failed to start container"

**Problem**: Container Fehler beim Start

**Lösungen**:
1. Logs anschauen
```bash
docker-compose logs fritz_exporter
docker-compose logs grafana
```

2. Spezifischen Container starten
```bash
docker-compose up -d fritz_exporter
```

3. Cache löschen und neu bauen
```bash
docker-compose down -v
docker-compose build --no-cache
docker-compose up -d
```

---

### Prometheus

#### ❌ "Targets down" in Prometheus UI

**Problem**: Exporter kann nicht erreicht werden

**Lösungen**:
1. Überprüfe Exporter Health
```bash
curl http://localhost:8000/health
```

2. Überprüfe Prometheus Config
```bash
curl http://localhost:9090/api/v1/targets
```

3. Logs des Exporters prüfen
```bash
docker-compose logs fritz_exporter | tail -50
```

4. Netzwerk-Konnektivität testen
```bash
docker exec fritz_exporter curl prometheus:9090
```

---

#### ❌ "No data in graphs"

**Problem**: Prometheus hat keine Metriken

**Lösungen**:
1. Warten Sie 2-3 Minuten (First Scrape Interval)
2. Überprüfe Exporter aktiv ist
```bash
curl http://localhost:8000/metrics | head -20
```

3. Überprüfe Scrape Config in `config/prometheus.yml`
4. Prometheus neustart
```bash
docker-compose restart prometheus
```

---

### Grafana

#### ❌ "Cannot login"

**Default Credentials**:
- Username: `admin`
- Password: `admin`

**Lösungen**:
1. Passwort zurücksetzen (Docker)
```bash
docker-compose down
# Ändern in docker-compose.yml:
# GF_SECURITY_ADMIN_PASSWORD=new_password
docker-compose up -d
```

2. Admin User neu erstellen
```bash
docker exec fritz_grafana grafana-cli admin reset-admin-password newpassword
```

---

#### ❌ "Datasource not available"

**Problem**: Prometheus Datasource disconnected

**Lösungen**:
1. Prometheus läuft?
```bash
docker-compose ps prometheus
```

2. Datasource Config prüfen
```
Grafana Settings → Data Sources → Prometheus
URL: http://prometheus:9090
```

3. Connectivity testen
```bash
docker exec fritz_grafana curl prometheus:9090
```

---

#### ❌ "Dashboard not loading"

**Problem**: Dashboard zeigt keine Daten

**Lösungen**:
1. Überprüfe Metrik Namen in PromQL
2. Dashboard Queries anpassen
3. Zeitbereich erweitern (z.B. "Last 24 hours")
4. Dashboard neu laden (F5)

---

### Python Exporter

#### ❌ "ModuleNotFoundError"

**Problem**: Poetry Dependencies nicht installiert

**Lösungen**:
1. Dependencies installieren
```bash
poetry install
```

2. Virtual Environment aktivieren
```bash
poetry shell
```

3. Oder direkt ausführen
```bash
poetry run fritz-monitor run
```

---

#### ❌ "Connection error from fritzconnection"

**Problem**: fritzconnection kann sich nicht verbinden

**Lösungen**:
1. Debug-Logging aktivieren
```bash
LOG_LEVEL=DEBUG poetry run fritz-monitor run
```

2. Fritz!Box TR-064 API prüfen
   - Web Interface: System → Einstellungen → Zugänge
   - "Zugriff für Anwendungen" aktivieren

3. Benutzer mit Admin-Rechten nutzen

---

#### ❌ "Process keeps restarting"

**Problem**: Docker Container restartet ständig

**Lösungen**:
1. Logs detailliert anschauen
```bash
docker-compose logs -f fritz_exporter
```

2. Environment Variablen prüfen
```bash
docker-compose exec fritz_exporter env | grep FRITZ
```

3. Password Encoding überprüfen (keine Sonderzeichen?)
4. Container im Debug-Modus starten
```bash
docker-compose run --rm fritz_exporter /bin/bash
```

---

### Logging & Debugging

#### Logs anschauen

```bash
# Alle Services
docker-compose logs

# Spezifischer Service
docker-compose logs fritz_exporter

# Laufende Logs (follow)
docker-compose logs -f fritz_exporter

# Letzte N Zeilen
docker-compose logs --tail=100

# Mit Timestamps
docker-compose logs --timestamps
```

#### Debug Mode aktivieren

```bash
# Exporter
LOG_LEVEL=DEBUG docker-compose up fritz_exporter

# oder in .env
LOG_LEVEL=DEBUG
```

#### Metriken manuell testen

```bash
# Von außen
curl -s http://localhost:8000/metrics | grep fritzbox

# Oder von inside docker
docker exec fritz_exporter curl localhost:8000/metrics | grep fritzbox
```

---

### Performance

#### ❌ "High CPU/Memory Usage"

**Lösungen**:
1. Scrape Interval erhöhen
```yaml
# config/prometheus.yml
global:
  scrape_interval: 120s  # Statt 60s
```

2. Retention Period reduzieren
```yaml
command:
  - '--storage.tsdb.retention.time=7d'  # Statt 15d
```

3. Metrics limitieren (nur wichtige scrapen)

---

### Network & Docker Compose

#### ❌ "Services können nicht miteinander kommunizieren"

**Problem**: Container können sich nicht untereinander erreichen

**Lösungen**:
1. Netzwerk prüfen
```bash
docker network ls
docker network inspect fritz_network
```

2. Service Namen richtig?
```bash
# Service Name = Container Service Name in docker-compose.yml
# Z.B.: prometheus, grafana, fritz_exporter
```

3. Netzwerk neu erstellen
```bash
docker-compose down -v
docker-compose up -d
```

---

## Checkliste für Debugging

- [ ] Docker läuft?
- [ ] .env Datei existiert und ist korrekt?
- [ ] Fritz!Box IP und Credentials richtig?
- [ ] Ports verfügbar (3000, 8000, 9090, 9093, 8086)?
- [ ] Fritz!Box antwortet auf Ping?
- [ ] Exporter Health Check erfolgreich?
- [ ] Prometheus Targets "up"?
- [ ] Grafana Datasource "Health OK"?
- [ ] Logs zeigen Fehler?

---

## Hilfreiche Commands

```bash
# Alle Container Status
docker-compose ps

# Einen Service neustarten
docker-compose restart fritz_exporter

# Container neu bauen
docker-compose up -d --build

# Alles zurücksetzen
docker-compose down -v

# Shell im Container
docker-compose exec fritz_exporter /bin/bash

# Logs streamen
docker-compose logs -f

# Metrics live prüfen
watch -n 5 'curl -s http://localhost:8000/metrics | grep fritzbox'
```

---

## Getting Help

1. **Logs anschauen**: Meist die beste Quelle für Fehler
2. **GitHub Issues**: Ähnliche Probleme haben andere?
3. **Community**: Docker/Prometheus/Grafana Forums
4. **StackOverflow**: Mit Tags: docker, prometheus, grafana

---

**Letzte Aktualisierung**: 30. November 2025
