# Feature map

Each row is one vertical slice: the thing that produces the data → the rules
that shape/alert on it → where you look at it. Files stay in their tool-native
locations (Prometheus rules, Grafana provisioning, compose services); this table
is the index that ties a slice together.

Ports are on the `backend` network unless noted. "Profile" is the
`COMPOSE_PROFILES` entry that enables an opt-in service (blank = always on).

## Core network (FRITZ!Box)

| Slice | Source | Rules | Dashboard | Key alerts |
|---|---|---|---|---|
| Router / WAN / mesh | `fritz-exporter` :8000 | `fritz_recording_rules.yml`, `fritz_alerts.yml` | `fritz_noc`, `fritz_mesh`, `fritz_client` | `Fritz*`, `WanSaturated*` |
| Path probes (ICMP/DNS/HTTP) | `blackbox-exporter` :9115 | `probe_rules.yml`, `http_probe_rules.yml` | `fritz_probes` | `Probe*`, `HTTP*` |
| Event log → Loki | `fritz-exporter` (EMIT_DEVICE_LOG) → `loki` :3100 | `config/loki/rules/` | `fritz_events` | log-based |
| Network health score | recording only | `health_rules.yml` | `network_health` | `NetworkHealth{Degraded,Critical}` |
| SLOs & error budgets | derived from health SLIs | `slo_rules.yml` | `home_slo` | `SLOFastBurn`, `SLOSlowBurn`, `SLOBudgetExhausted` |
| Baseline / anomaly | recording + subqueries | `anomaly_rules.yml` | `network_health`, `lantap_bandwidth` | `DeviceTrafficSpike`, `EnergyCostSpike`, … |
| New-device detection | `netwatch-exporter` :9133 | `netwatch_alerts.yml` | `fritz_events` | `NewDeviceOnWiFi`, `ManyNewDevices` |
| Per-device bandwidth | `lantap-exporter` :9129 (profile `lantap`) | `lantap_alerts.yml` | `lantap_bandwidth` | `Lantap*` |
| Occupancy (derived) | recording only | `occupancy_rules.yml` | `network_health`, `home_kiosk` | `PhantomOccupancy` |

## Internet quality

| Slice | Source | Rules | Dashboard | Key alerts |
|---|---|---|---|---|
| Speedtest | `speedtest-exporter` :9125 (profile `speedtest`) | `http_probe_rules.yml` (`speedtest_alerts`) | `fritz_probes` | `Speedtest*` |
| Bufferbloat | `bufferbloat-exporter` :9132 (profile `bufferbloat`) | `bufferbloat_alerts.yml` | `fritz_probes` | `Bufferbloat{High,Severe}` |
| ISP SLA / contract | derived from speedtest + line rate | `isp_sla_rules.yml` | `fritz_probes` | `ISPSpeed{BelowContract,ChronicallyLow}` |
| External probe (off-site) | `.github/workflows/external-probe.yml` | — | GH job summary | ntfy on failure |

## Smart home (profile `smarthome`, or per-vendor)

| Slice | Source | Rules | Dashboard | Key alerts |
|---|---|---|---|---|
| Hue | `hue-exporter` :9120 | `smarthome_alerts.yml` | `smarthome_fleet` | `Smarthome*` |
| Bosch SHC (power + climate + safety) | `bosch-exporter` :9121 | `climate_rules.yml`, `climate_alerts.yml`, `smarthome_alerts.yml` | `home_climate`, `smarthome_fleet` | `Bosch*`, `Room*` |
| Blink cameras | `blink-exporter` :9122 | `smarthome_alerts.yml` | `smarthome_fleet` | `Blink*` |
| FRITZ!DECT plugs | `fritzdect-exporter` :9123 | `smarthome_alerts.yml`, `energy_rules.yml` | `smarthome_fleet`, `home_energy` | `Smarthome*` |
| Weather | `weather-exporter` :9124 | `climate_rules.yml` | `home_climate` | — |
| Electricity price + consumption | `energy-exporter` :9128 | `energy_rules.yml` | `home_energy` | `Energy*` |
| Solar / PV (Sungrow) | `sungrow-exporter` :9135 | `sungrow_rules.yml` | `home_energy` | `SungrowExporterDown`, `SolarNoProductionMidday`, `InverterOverheating` |
| Home automation (dry-run) | `automation` :9131 (profile `automation`) | `automation_alerts.yml` | — | `Automation{Stalled,ActionFailing,RunningLive}` |

## Host & stack

| Slice | Source | Rules | Dashboard | Key alerts |
|---|---|---|---|---|
| Host metrics | `node-exporter` :9100 | `host_alerts.yml` | `host_health` | `Host*` |
| Containers | `dockerstats-exporter` :9126 → `docker-socket-proxy` :2375 | `host_alerts.yml` (`container_alerts`) | `host_health` | `Container*` |
| Long-term store | `victoriametrics` :8428 (remote_write target) | — | any (2nd datasource) | — |
| Stack self-monitoring | `prometheus` self-scrape | `meta_rules.yml` | `stack_overhead` | `PrometheusHighCardinality`, `PrometheusRuleEvalFailing` |
| CVE scan | `trivy` (weekly) → node-exporter textfile | `security_alerts.yml` | `host_health` | `ImageHasCriticalCVEs` |
| Backups + verification | `backup` (restic) → node-exporter textfile | `backup_alerts.yml` | `host_health` | `Backup{Stale,Failing,VerifyFailed}` |

## Alerting & delivery

| Slice | Source | Rules | Dashboard | Key alerts |
|---|---|---|---|---|
| Alertmanager → ntfy | `alertmanager` :9093 → `alertbridge` :9127 | severity routing in `alertmanager.yml` | — | — |
| Dead-man's-switch | `Watchdog` always-fires → `alertbridge /watchdog` | `watchdog.yml` | — | `AlertingPipelineStalled`, `AlertmanagerNotConnected` |
| Outage annotations | `annotator` :9134 → Grafana API | `annotator_alerts.yml` | all (annotation layer, tag `outage`) | `Annotator{GrafanaErrors,Stalled}` |
| Weekly / monthly digest | `digest` :9130 → ntfy | — | — | — |

## Edge (opt-in)

| Slice | Source | Notes |
|---|---|---|
| Reverse proxy | `caddy` (profile `proxy`) | LAN-only allowlist, internal TLS |
| Device manager UI | `device-manager` :8080 (profile `admin`) | block/unblock hosts |
| iperf reference | `iperf-probe` (profile `iperf`) | LAN throughput baseline |

---

**Layout**: `compose.prod.yml` is a thin `include:` of `compose/{core,exporters,
host,apps}.yml` — still one project, run it exactly as before
(`docker compose -f compose.prod.yml …`). Prometheus rules are one file per
concern under `config/prometheus/rules/`, loaded by a `*.yml` glob (so
`prometheus.yml`, `deploy.sh` and CI pick up a new file with no edit).

**Adding a slice**: new exporter under `src/home_iot/<name>/`, a service in the
matching `compose/<part>.yml`, a scrape job in `config/prometheus.yml`, a
`rules/<name>_*.yml`, optionally a dashboard JSON, then a row here.
