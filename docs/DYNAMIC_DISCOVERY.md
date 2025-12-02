# Dynamische Mesh-Erkennung

Das System erkennt **automatisch alle Geräte und Mesh-Nodes** - ohne manuelle Konfiguration!

## 🚀 Vollautomatische Erkennung

### Was wird AUTOMATISCH erkannt:

✅ **Mesh-Nodes (Infrastruktur)**:
- Router (Fritz!Box)
- Alle Repeater (WLAN, 2400, 3000 AX, 6000, etc.)
- Powerline-Adapter (1220, 1260, etc.)
- Hierarchie (welcher Node ist Parent von welchem)
- IP-Adressen
- MAC-Adressen
- Geräte-Modelle

✅ **Client-Geräte**:
- Alle verbundenen Geräte
- Online/Offline Status
- IP-Adressen (dynamisch via DHCP)
- MAC-Adressen
- Verbindungstyp (WLAN/LAN/Guest)
- Zuordnung zu Nodes (welches Gerät ist mit welchem Repeater verbunden)

### Wie funktioniert die automatische Zuordnung?

**Priorität 1: WLAN Association (WiFi-Geräte)**
- Fritz!Box API liefert: Welches Gerät ist mit welchem Access Point verbunden
- Funktioniert für alle WiFi-Clients
- Automatische Aktualisierung bei Roaming

**Priorität 2: Mesh Topology IP (LAN-Geräte)**
- API zeigt IP-Adressen pro Mesh-Node
- Funktioniert für kabelgebundene Geräte

**Priorität 3: Default Router**
- Wenn keine Zuordnung möglich: Gerät ist am Hauptrouter

## 📝 Optionale Overrides

In **99% der Fälle** ist keine Config nötig! Nur für Spezialfälle:

### `config/network_topology.json` (optional!)

```json
{
  "static_ip_to_repeater": {
    "192.168.178.100": "Keller-Repeater"
  },
  "manual_hierarchy": {
    "AA:BB:CC:DD:EE:FF": "fritz.box"
  },
  "model_name_mapping": {
    "Garage": "FRITZ!Repeater 6000"
  }
}
```

**Wann brauchst du das?**
- `static_ip_to_repeater`: Nur wenn API keine Zuordnung liefert (sehr selten)
- `manual_hierarchy`: Nur wenn API falsche Parent-Child-Beziehung erkennt (fast nie)
- `model_name_mapping`: Nur für schönere Namen (optional)

## ✨ Plug & Play

### Neues Gerät hinzufügen:

1. Gerät mit Fritz!Box verbinden
2. **FERTIG!** ✅

Das war's. Keine Config, kein Neustart, keine Anpassungen.

### Repeater hinzufügen:

1. Repeater mit Fritz!Box Mesh verbinden
2. **FERTIG!** ✅

Wird automatisch erkannt mit:
- Name
- Typ (Repeater/Powerline)
- Position in Hierarchie
- Alle verbundenen Geräte

### IP-Adresse ändert sich:

**Kein Problem!** Das System nutzt:
- MAC-Adressen (bleiben gleich)
- WLAN-Assoziationen (unabhängig von IPs)
- Automatische DHCP-Updates

## 🔄 Dynamische Updates

Das System aktualisiert sich automatisch:

- **Mesh Discovery**: Alle 5 Minuten
- **Device States**: Bei jedem Prometheus Scrape
- **Neue Geräte**: Sofort erkannt
- **IP-Wechsel**: Sofort aktualisiert

## 🎯 Best Practices

### ✅ DO:
- Einfach Geräte hinzufügen/entfernen
- Fritz!Box DHCP nutzen
- Mesh-Nodes über Fritz!Box WebUI verbinden
- System ohne Config laufen lassen

### ❌ DON'T:
- Keine statischen Overrides ohne Grund
- Keine manuellen MAC-Listen pflegen
- Keine IP-Mappings hardcoden

## 🐛 Troubleshooting

**Problem: Gerät wird nicht erkannt**
1. Check: Ist es wirklich mit Fritz!Box verbunden?
2. Check: Ist es in Fritz!Box WebUI sichtbar?
3. Warte 5 Minuten (nächster Discovery-Scan)

**Problem: Falsche Node-Zuordnung**
1. Check Fritz!Box WebUI: Zeigt es auch dort falsch?
2. Wenn API falsch: Nutze `static_ip_to_repeater` Override
3. Melde Bug an AVM (API-Problem)

**Problem: Neue Mesh-Node nicht sichtbar**
1. Check: Ist Mesh-Verbindung aktiv? (Fritz!Box WebUI)
2. Warte 5 Minuten (Discovery läuft periodisch)
3. Restart: `docker-compose restart mesh_discovery`

## 📊 Monitoring

Sieh in Grafana wie viele Geräte automatisch erkannt wurden:

- **Total Devices**: Alle jemals gesehenen
- **Online Devices**: Aktuell verbunden
- **Mesh Nodes**: Infrastruktur
- **Connection Details**: Wo ist was verbunden

Alles ohne Config! 🎉
