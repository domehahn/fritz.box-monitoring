# Colima Setup Guide

Anleitung für das Einrichten von Colima als Docker Engine für das Fritz!Box Monitoring System.

## 📋 Was ist Colima?

**Colima** = Container Lima  
Ein leichtgewichtiger Docker-Engine für macOS, der statt Docker Desktop eine effizientere virtualisierte Umgebung bietet.

### Vorteile gegenüber Docker Desktop
- ✅ Weniger RAM-Verbrauch
- ✅ Bessere Performance
- ✅ Open Source
- ✅ Einfach zu installieren
- ✅ Vollständig kompatibel mit Docker

---

## 🚀 Schnelle Installation

### Schritt 1: Colima installieren

```bash
# Mit Homebrew (empfohlen)
brew install colima

# Oder mit MacPorts
sudo port install colima

# Oder: Manuell von GitHub
# https://github.com/abiosoft/colima/releases
```

### Schritt 2: Docker CLI installieren

```bash
# Docker CLI (nicht Docker Desktop!)
brew install docker

# Optionale Tools
brew install docker-compose
```

### Schritt 3: Setup-Skript ausführen

```bash
cd ~/dev/workspace/fritz.box-monitoring

# Mit Bash Script
chmod +x setup-colima.sh
./setup-colima.sh

# Oder mit Python (cross-platform)
python3 setup-colima.py

# Mit Custom Ressourcen
./setup-colima.sh --cpu 6 --memory 8 --disk 100
```

---

## 🎛️ Ressourcen-Konfiguration

### Standard Setup (Default)
```bash
./setup-colima.sh
# Ergebnis: 4 CPU, 6GB RAM, 50GB Disk
```

### High-Performance Setup
```bash
./setup-colima.sh --cpu 8 --memory 16 --disk 100
```

### Minimal Setup (für schwache Macs)
```bash
./setup-colima.sh --cpu 2 --memory 4 --disk 30
```

### Environment Variablen
```bash
# Oder mit Umgebungsvariablen
export COLIMA_CPU=6
export COLIMA_MEMORY=8
export COLIMA_DISK=100
./setup-colima.sh
```

---

## 🛠️ Häufige Commands

### Status & Verwaltung

```bash
# Colima Status anschauen
colima status

# Colima Logs anschauen
colima logs

# Colima neustarten
colima restart

# Colima stoppen
colima stop

# Colima starten
colima start

# Colima löschen (warnung: alle Daten gehen verloren)
colima delete
```

### Docker Commands (funktionieren normal)

```bash
# Docker Info
docker info

# Container anschauen
docker ps

# Images anzeigen
docker images

# Logs eines Containers
docker logs container_name

# Container Stats
docker stats
```

### Fritz!Box Monitoring mit Colima

```bash
# Services starten
docker-compose up -d

# Status prüfen
docker-compose ps

# Logs anschauen
docker-compose logs -f

# Services stoppen
docker-compose down
```

---

## 🔧 Troubleshooting

### Problem: "colima: command not found"

**Lösung**: Colima nicht installiert
```bash
brew install colima
```

### Problem: "Cannot connect to Docker daemon"

**Lösung**: Colima läuft nicht
```bash
# Colima starten
colima start

# Oder mit spezifischem Profil
colima start fritz-monitoring
```

### Problem: "Docker commands are slow"

**Lösung**: Disk oder Memory Limits erreicht
```bash
# Status anschauen
colima status

# Ressourcen erhöhen
colima delete
colima start --cpu 6 --memory 8 --disk 100
```

### Problem: "Port already in use"

**Lösung**: Port wird von anderem Service genutzt
```bash
# Find process
lsof -i :3000

# Oder Colima neustarten
colima restart
```

### Problem: "Out of disk space"

**Lösung**: Disk ist voll
```bash
# Docker Cleanup
docker system prune -a

# Oder: Disk erweitern
colima delete
colima start --disk 100
```

---

## 📊 Performance Tuning

### CPU & Memory

```bash
# Aktuelle Einstellungen anschauen
colima status

# Ändern (muss Colima neu starten)
colima stop
colima start --cpu 8 --memory 16
```

### Disk Performance

```bash
# Schnellere VM (QEMU default)
# Bereits optimiert

# Bei Problemen: Cache löschen
docker system prune -a --volumes
colima restart
```

### Network

```bash
# Colima mit Network-Address starten (auto in setup script)
colima start --network-address

# Netzwerk-Status prüfen
colima status
```

---

## 🔐 Security Best Practices

1. **Nur lokal verwenden**
   - Colima ist nicht für Remote-Zugriff konzipiert
   - Nutze Reverse Proxy für externe Zugriffe

2. **Regelmäßige Updates**
   ```bash
   brew upgrade colima
   brew upgrade docker
   ```

3. **Image Scanning**
   ```bash
   # Vor Production: Images überprüfen
   docker scan image_name
   ```

---

## 📈 Monitoring der Colima VM

### System-Resourcen

```bash
# Live Überwachung
docker stats

# VM Status
colima status

# Disk Usage
docker system df
```

### Logs

```bash
# Colima Logs
colima logs

# Docker Daemon Logs
docker logs

# Compose Logs
docker-compose logs
```

---

## 🔄 Migration von Docker Desktop zu Colima

### Schritt 1: Docker Desktop stoppen

```bash
# Quit Docker Desktop
# Oder: Beende alle Container
docker-compose down
docker system prune -a
```

### Schritt 2: Colima installieren und starten

```bash
brew install colima
./setup-colima.sh
```

### Schritt 3: Images & Volumes übernehmen

```bash
# Docker Desktop exportieren
docker save $(docker images -q) | docker load

# Oder: Volumen manuell kopieren
docker volume ls
```

### Schritt 4: Services neu starten

```bash
docker-compose up -d
```

---

## 🎓 Weiterführende Ressourcen

- **Colima GitHub**: https://github.com/abiosoft/colima
- **Colima Docs**: https://github.com/abiosoft/colima#readme
- **Docker Docs**: https://docs.docker.com/
- **Docker Compose**: https://docs.docker.com/compose/

---

## 💡 Tipps & Tricks

### Colima in Hintergrund starten

```bash
# Einmalig Setup
colima start

# Dann automatisch starten
# → Colima startet automatisch mit nächstem Docker Befehl
```

### Mehrere Colima Profile

```bash
# Verschiedene Profile für verschiedene Projekte
colima start profile1 --cpu 4 --memory 6
colima start profile2 --cpu 8 --memory 12

# Zwischen Profilen wechseln
colima stop profile1
colima start profile2
```

### Colima mit Aliases

```bash
# In ~/.zshrc oder ~/.bash_profile
alias colima-start='colima start fritz-monitoring'
alias colima-stop='colima stop'
alias colima-logs='colima logs'

# Dann benutzen
colima-start
```

### System-Integration

```bash
# Automatisch starten beim Boot
# (Nicht nativ supported, aber:)
# Erstelle einen LaunchAgent in ~/Library/LaunchAgents/

cat > ~/Library/LaunchAgents/com.abiosoft.colima.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.abiosoft.colima</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/colima</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

# Aktivieren
launchctl load ~/Library/LaunchAgents/com.abiosoft.colima.plist
```

---

## 📝 Script-Optionen Reference

### setup-colima.sh

```bash
./setup-colima.sh [OPTIONS]

Options:
    -h, --help          Show help message
    -v, --verbose       Enable verbose logging
    --cpu <num>         Number of CPU cores (default: 4)
    --memory <num>      Memory in GB (default: 6)
    --disk <num>        Disk size in GB (default: 50)
```

### setup-colima.py

```bash
python3 setup-colima.py [OPTIONS]

Options:
    -h, --help              Show help message
    -v, --verbose           Enable verbose logging
    --cpu <num>             Number of CPU cores (default: 4)
    --memory <num>          Memory in GB (default: 6)
    --disk <num>            Disk size in GB (default: 50)
    --profile <name>        Colima profile name (default: fritz-monitoring)
```

---

**Letzte Aktualisierung**: 30. November 2025
