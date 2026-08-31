# Observability extensions (P1–P5)

Five additions layered on the FRITZ!Box NOC + smart-home exporters.

| # | What | New services | Dashboards | Rules | Opt-in? |
|---|------|--------------|-----------|-------|---------|
| P1 | Host & container monitoring | `node-exporter`, `cadvisor` | **Stack Host & Containers** | `host_alerts.yml` | no (always on) |
| P2 | Bosch power + room climate | (extends `bosch-exporter`) | **Home Climate & Energy** | `climate_rules.yml`, `climate_alerts.yml` | no (needs `--profile bosch`) |
| P3 | Weather (DWD / Bright Sky) | `weather-exporter` | *Weather* row on Home Climate | – | `--profile weather` |
| P4 | Speedtest + HTTP/TLS probes | `speedtest-exporter`, `probe_http` job | *speedtest* row on Network Path Probes | `http_probe_rules.yml` | speedtest: `--profile speedtest`; HTTP: always |
| P5 | FRITZ!Box event log → Loki | (extends `fritz-exporter`) | Network Events & Forensics (`fritzbox_log`) | – | on by default |

---

## P1 · Host & containers

* **node-exporter** — CPU / memory / disk / network of the machine the engine
  runs on. On Docker Desktop / macOS this is the **Linux VM**, not the Mac, but
  its disk & memory headroom is what the stack actually lives in.
* **cAdvisor** — per-container CPU, memory, restarts, OOM kills (works on any OS).

Alerts: `HostDiskAlmostFull` / `HostDiskWillFill` (3-day linear projection),
`HostHighCPU`, `HostLowMemory`, `ContainerKilledOOM`,
`ContainerFrequentRestarts`, `ContainerHighMemory`.

## P2 · Bosch power + climate

The `bosch-exporter` now also reads:

| Metric | Source |
|--------|--------|
| `bosch_device_power_watts`, `bosch_device_energy_watt_hours_total` | `PowerMeter` (metering plugs) |
| `bosch_shc_total_power_watts` | sum of the above |
| `bosch_device_contact_open` | `ShutterContact` (windows / doors) |
| `bosch_device_setpoint_celsius` | `RoomClimateControl` |
| `bosch_device_air_purity_ppm`, `bosch_device_air_rating` | `AirQualityLevel` (TWINGUARD) |
| `bosch_device_smoke_alarm`, `bosch_shc_smoke_alarm_count` | `SmokeDetectorCheck` / `Alarm` |
| `bosch_intrusion_armed` / `_alarm` / `_available`, `bosch_surveillance_alarm` | intrusion / surveillance systems |

Recording rules build per-**room** aggregates and a **dew-point margin**
(`room:dew_point_margin:kelvin`, Magnus formula) — below ~3 K on a cold wall is
condensation / mould risk.

Alerts: `BoschWindowOpenWhileHeating` (contact open ∧ a radiator in the same
room running — the direct money-saver), `RoomMouldRisk`, `RoomHighHumidity`,
`RoomTooCold`, `BoschAirQualityBad`, and **critical** `BoschSmokeAlarm` /
`BoschIntrusionAlarm` / `BoschSurveillanceAlarm`.

Room names are resolved from the SHC (`session.rooms`); devices with no room
fall back to the raw room id.

## P3 · Weather

`weather-exporter` polls **Bright Sky** (`api.brightsky.dev`, DWD data, no API
key). Set your location:

```ini
WEATHER_LAT=52.520
WEATHER_LON=13.405
# or: WEATHER_STATION=<dwd station id>
```
```bash
docker compose -f compose.prod.yml --profile weather up -d --build
```

Metrics: `weather_temperature_celsius`, `_humidity_percent`, `_wind_speed_kmh`,
`_wind_gust_kmh`, `_precipitation_mm`, `_cloud_cover_percent`, `_pressure_hpa`,
`_solar_kwh_m2`, `weather_condition_info{condition,icon}`. Overlaid on room
temperature / valve % for a degree-day view of heating demand.

## P4 · Speedtest + HTTP/TLS probes

**Speedtest** (`speedtest-exporter`, `--profile speedtest`) — Cloudflare speed
test, no Ookla binary. Bandwidth-heavy: interval floored at 1800 s, default
3600 s, ~`SPEEDTEST_MAX_MB` (100) down + half up per run. Shows *achievable
capacity vs the contract*; the always-on WAN byte-rate metrics show *actual
usage*. Metrics: `speedtest_download_bits_per_second`, `_upload_...`,
`_latency_seconds`, `_jitter_seconds`.

**HTTP probes** (`probe_http` job, always on) — edit
`config/blackbox/targets/http_services.yml` (file_sd, hot-reloaded) with the
services you care about (kids' game-server login, work VPN portal, NAS, bank).
Every HTTPS target also yields `probe_ssl_earliest_cert_expiry` →
`TLSCertExpiringSoon` (< 21 days) / `TLSCertExpired`.

## P5 · FRITZ!Box event log → Loki

The collector now also pulls `DeviceInfo1:GetDeviceLog` every 5 minutes and
ships **new** lines to Loki as structured events (`event_type="fritzbox_log"`,
`subsystem` ∈ wan/wifi/dect/security/system, severity from keywords). Real box
events — WAN reconnects, Wi-Fi logins, DECT pairings, forced reconnections,
firmware — instead of only the snapshot-derived ones.

Needs the monitoring user to have **"FRITZ!Box Settings"** permission (same one
that unlocks mesh topology). The first poll after start only establishes the
baseline. Disable with `emit_device_log=False` on `CollectorService` if not
wanted.

Query in Grafana Explore / Network Events & Forensics:

```logql
{service="fritz-exporter"} |= "fritz_event " | pattern "<_>fritz_event <ev>" | line_format "{{.ev}}" | json | event_type="fritzbox_log"
```
