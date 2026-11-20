# FRITZ!Box Production Monitoring Stack

Production-grade observability stack for AVM FRITZ!Box routers, mesh repeaters, and powerline adapters using Prometheus, Grafana, Loki, Tempo, Grafana Alloy, Cloudflare Zero Trust, and `fritz-avm-client`.

---

## Features

- **Full LGTM Observability Stack**: Prometheus (metrics), Loki (logs), Tempo (traces), Grafana (dashboards) and Grafana Alloy with correlation between logs and traces.
- **Deep Mesh Diagnostics & Offline/Power-Loss Detection**: Persistent inventory of all known repeaters, detection of offline/unplugged repeaters, multi-hop hierarchy, link speed matrix (RX/TX), and band-fallback root-cause analysis.
- **Cloudflare Zero Trust & Tunnel**: Secure remote access with zero open router ports, Cloudflare Access authentication, and Grafana Auth-Proxy Single Sign-On.
- **Decoupled Architecture**: Asynchronous background collector with atomic snapshot swaps. Fast, deterministic `/metrics` scrapes without TR-064 timeouts.
- **Syslog Logging Pipeline**: RFC3164 Syslog UDP ingestion via Grafana Alloy to Loki (persisted under `/loki` TSDB v13).
- **Hardened Device Manager**: Optional web UI (Profile `admin`) secured with HTTP Basic/Session auth, CSRF protection, and MAC address validation.
- **Supply Chain Security**: Multi-stage non-root containers, dropped Linux capabilities (`cap_drop: ALL`), Docker Secrets, and zero floating tags.

---

## Quick Start (Production)

1. Create secret files:
   ```bash
   mkdir -p secrets
   echo "my_fritz_password" > secrets/fritz_password.txt
   echo "my_grafana_password" > secrets/grafana_admin_password.txt
   echo "my_device_manager_password" > secrets/device_manager_admin_password.txt
   ```

2. Copy production environment file:
   ```bash
   cp .env.production.example .env.production
   ```

3. Launch production stack:
   ```bash
   docker compose --env-file .env.production -f compose.prod.yml up -d
   ```

4. Access Grafana at `http://127.0.0.1:3000`.

---

## Documentation

### Network Observability / NOC

- [Current State & Gap Analysis](docs/network-observability-current-state.md)
- [Metric Catalogue](docs/fritz-metrics.md)
- [Dashboards & Alerts](docs/dashboards.md)
- [Cloudflare Zero Trust & Remote Access Guide](docs/CLOUDFLARE_ZERO_TRUST.md)
- [Event Pipeline](docs/event-pipeline.md)
- [FRITZ!Box Account Permissions](docs/fritz-permissions.md) — grant these to unlock mesh / Wi-Fi / event-log data
- [iperf3 LAN reference (opt-in)](docs/iperf-reference.md)
- [Smart-home exporters — Hue / Bosch / Blink / FRITZ!DECT (opt-in)](docs/smart-home-exporters.md)
- [Observability extensions — host/container, room climate, weather, speedtest, box event log (P1–P5)](docs/observability-extensions.md)
- [Feature map — exporter → rules → dashboard → alerts, per slice](docs/features.md)
- [Troubleshooting Playbook](docs/troubleshooting.md)

Primary dashboards: **Home Network NOC** (`/d/fritz_noc`), **Client Diagnostics**
(`/d/fritz_client`), **Mesh Infrastructure** (`/d/fritz_mesh`), **Network Path
Probes** (`/d/fritz_probes`), **Network Events & Forensics** (`/d/fritz_events`).

### Stack

- [Architecture Guide](file:///Users/dominikhahn/dev/workspace/fritz.box-monitoring/docs/ARCHITECTURE.md)
- [Production Deployment Guide](file:///Users/dominikhahn/dev/workspace/fritz.box-monitoring/docs/PRODUCTION.md)
- [Security Guide](file:///Users/dominikhahn/dev/workspace/fritz.box-monitoring/docs/SECURITY.md)
- [Operations & Runbook](file:///Users/dominikhahn/dev/workspace/fritz.box-monitoring/docs/RUNBOOK.md)
- [Backup & Restore Guide](file:///Users/dominikhahn/dev/workspace/fritz.box-monitoring/docs/BACKUP_RESTORE.md)
- [Migration Guide](file:///Users/dominikhahn/dev/workspace/fritz.box-monitoring/docs/MIGRATION.md)
- [Production Readiness Report](file:///Users/dominikhahn/dev/workspace/fritz.box-monitoring/PRODUCTION_READINESS_REPORT.md)
