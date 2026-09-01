# Observability extensions (P0–P5)

Five additions layered on the FRITZ!Box NOC + smart-home exporters.

| # | What | New services | Dashboards | Rules | Opt-in? |
|---|------|--------------|-----------|-------|---------|
| P0 | Alerting -> phone | `alertmanager`, `alertbridge` | – | `config/alertmanager/` | no (silent until `NTFY_TOPIC` set) |
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

---

## P0 · Alerting -> ntfy

Nothing above matters if the alerts fire into the void. Now:

```
Prometheus rule -> Alertmanager -> alertbridge -> ntfy -> phone
```

* **alertmanager** (`prom/alertmanager`) — routing tree by `severity`:
  * `critical` (smoke, intrusion, WAN down, disk full, TLS expired) → immediately, one message each, repeat hourly
  * `warning` → grouped, at most every 5 min, repeat every 4 h
  * `info` (high humidity, cert expiring in 21 d, slow HTTP, Hue bulb off the mesh) → grouped, hourly, repeat daily
  * a `critical` inhibits a same-name `warning`/`info`
* **alertbridge** (`home_iot.alertbridge`) — Alertmanager has no ntfy receiver and ntfy does not parse the webhook JSON, so this ~120-line service reformats each alert into a titled ntfy push (priority 5/4/2 by severity, `✅` on resolve).

### Setup

1. Pick a long random topic (treat it like a password — anyone who knows it can read your alerts) and set it:
   ```ini
   NTFY_TOPIC=fritz-mon-<random>
   ```
2. Subscribe in the ntfy app (iOS / Android / web) to `https://ntfy.sh/<topic>`.
3. `docker compose ... up -d alertmanager alertbridge` (they are in the default profile).
4. Smoke test: `docker exec fritz-monitoring-prod-alertbridge-1 wget -qO- localhost:9127/test` → you should get a push.

For a private topic use your own ntfy server: `NTFY_URL=https://ntfy.example.com` + `NTFY_TOKEN` (literal, or a `/secrets/...` path).

Alertmanager UI is on `backend` only; reach it with `docker exec ... wget` or add a port mapping if you want the web view.


---

## P2 · Log-based alerts (Loki ruler)

Loki's built-in ruler evaluates LogQL and pushes to the **same Alertmanager**
the Prometheus rules use. Rules: `config/loki/rules/fake/log_alerts.yml`
(`fake` = the tenant Alloy writes as).

* `FritzBoxFailedLogins` — > 3 `Anmeldung … fehlgeschlagen/abgewiesen` in 15 min
  (router-UI / MyFRITZ brute force).
* `GrafanaAuthFailures` — > 5 failed Grafana logins / 15 min.
* `ContainerStackTrace` — any Python `Traceback (most recent call last)` in the
  stack logs.
* `AlloyDeliveryErrors` — Alloy `level=error` (logs may be dropping).
* `HighLogErrorRate` — > 50 error lines / 10 min across the stack (info).

Check the ruler:
`docker exec …-loki-1 wget -qO- localhost:3100/loki/api/v1/rules`

## P3 · Electricity price + consumption

`home_iot.energy` (:9128, always on). Price source, best first:

1. **Tibber** (`TIBBER_TOKEN` from developer.tibber.com) — real consumer price,
   `level`, today/tomorrow arrays, and last completed hour's kWh + €.
2. **aWATTar** (`ENERGY_MARKET=awattar_de|awattar_at`, no key) — hourly spot
   price; a rough consumer price is `spot × ENERGY_VAT + ENERGY_SURCHARGE_CT_KWH`.

Optional meter: **Shelly EM / 3EM / Pro 3EM** at `SHELLY_HOST` (Gen1 `/status`
and Gen2 `/rpc/Shelly.GetStatus` both handled) → live `energy_power_watts`,
per-phase, cumulative import/feed-in.

Metrics: `energy_price_eur_per_kwh`, `energy_spot_price_eur_per_kwh`,
`energy_price_level` (0–4), `energy_price_rank_today` (0 = cheapest hour),
`energy_price_min_next12h_eur_per_kwh`, `energy_power_watts`,
`energy_phase_power_watts`, `energy_import/export_watt_hours_total`,
`energy_last_hour_kwh` / `_cost_eur`.

Recording rules (`energy_rules.yml`): `home:known_load:watts` (Bosch plugs +
meter), `home:known_load_cost:eur_per_hour`. Alerts: `ElectricityExpensiveNow`
(rank > 0.85 → hold big loads), `ElectricityVeryCheapNow` (rank < 0.12 → good
time), `EnergyExporterDown`. Dashboard **Electricity Price & Consumption**.

## P4 · Long-term metrics (VictoriaMetrics)

`victoriametrics` single-node (always on). Prometheus `remote_write`s every
sample there; VM compresses ~7× and keeps `VM_RETENTION` months (default 24).
Grafana has it as a second Prometheus-type datasource **VictoriaMetrics**
(`uid: victoriametrics`) — switch any panel's datasource to it for history
beyond the local Prometheus window (`PROMETHEUS_RETENTION_TIME`, still 30 d).

## P5 · Occupancy (derived)

Recording rules only — no new data source. `occupancy_rules.yml`:

* `home:people_devices:count` — `fritz_device_up` for names matching a phone /
  watch regex (**tune it** to your household).
* `home:motion_recent:bool` — any `blink_camera_motion_detected` in 15 min.
* `home:occupied:bool` — phone present **or** recent motion.

Alerts: `RoomHeatingWhileAway` (valve > 30 % ∧ away 3 h — warning),
`PlugOnWhileAway` (info; ignore for fridges/servers), `MotionWhileEmpty` (motion
with no household phone on the network — smarter than the raw intrusion state).
A "Presence" row is added to the **Home Climate & Energy** dashboard.

---

## Per-device bandwidth (opt-in) — `home_iot.lantap`

TR-064 exposes no per-host throughput. This exporter opens the FRITZ!Box's own
continuous packet capture (`/cgi-bin/capture_notimeout`, UI session via PBKDF2
login), reads the pcap stream (the "modified" `0xa1b2cd34` variant FRITZ!OS
emits), and buckets `orig_len` by the local source / destination IP:

* `lantap_host_sent_bytes_total{ip}` / `_received_bytes_total{ip}` (+ `_packets_`)
* `lantap_host_info{ip,name,mac}` — IP → name from the FRITZ!Box host list

`rate(...) * 8` on the dashboard = live bit/s. Dashboard **Per-Device
Bandwidth** has top-talker charts, a per-device table (Mbit/s now + GB today),
and a `$device` drill-down.

**Caveats**
* **CPU load on the FRITZ!Box** — AVM does not support 24/7 capture. Small
  `LANTAP_SNAPLEN` (128) keeps the stream light (byte counts use the real
  packet length, not the captured bytes). Set `LANTAP_MAX_MINUTES` for an
  automatic stop.
* Needs the monitoring user's **"FRITZ!Box Settings"** permission (UI login).
* LAN-bridge capture (`1-lan`) sees LAN-local traffic too; use `LANTAP_IFACE=3-17`
  for internet-only per device.

```bash
docker compose -f compose.prod.yml --profile lantap up -d --build
# ... watch the dashboard ...
docker compose -f compose.prod.yml --profile lantap stop lantap-exporter
```
