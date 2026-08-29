# Production Readiness Report

## Executive Summary

- **Evaluation Rating**: **Production Ready**
- **Date**: 2026-08-29
- **Repositories**: `fritz-avm-client` (v0.2.0) & `fritz.box-monitoring` (v1.0.0)

Both repositories have been systematically refactored from prototype status into a unified, secure, observable, and reproducible software supply chain for AVM FRITZ!Box monitoring.

---

## Technical Changes & Improvements

### Architecture & Client Unification

- **Single SDK**: Removed embedded TR-064 code (`src/fritz_monitoring/avm/`) and `fritzconnection` direct dependency from `fritz.box-monitoring`. The monitoring stack imports `fritz-avm-client>=0.2.0` exclusively.
- **Asynchronous Snapshot Collection**: Replaced synchronous scrape-time TR-064 calls with `CollectorService` (30s background loop). `/metrics` reads strictly from an immutable, atomic `MonitoringSnapshot`.
- **Target Scraping Decoupling**: Removed direct TR-064 scraping on port `49000` and the legacy `mesh_discovery` container. Prometheus scrapes a single target (`fritz-exporter:8000`).

### Security & Hardening

- **Device Manager Protection**: Disabled by default (Compose profile `admin`). Secured with HTTP Basic/Session auth, CSRF token validation on POST requests, and strict MAC regex validation (`^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$`).
- **Secret Resolution**: Password resolution prioritizes `*_FILE` secrets (`/run/secrets/*`). No credentials appear in environment strings, log entries, or exception tracebacks.
- **Container Hardening**: All custom containers run non-root (`appuser` UID 10001), drop all Linux capabilities (`cap_drop: [ALL]`), enforce `no-new-privileges:true`, and set explicit CPU and memory resource limits.

### Observability & Logging

- **Syslog Pipeline**: Replaced `promtail` and `log_pusher` with Grafana Alloy syslog UDP listener (`loki.source.syslog` port 1514).
- **Loki Persistence**: Fixed storage paths under `/loki` (`/loki/chunks`, `/loki/rules`, `/loki/index`) with TSDB schema v13 and 30-day retention (`720h`).
- **Health Endpoints**: Implemented `/healthz` (200 Liveness) and `/readyz` (200 Readiness if snapshot age <= 120s, 503 Service Unavailable otherwise).

### CI/CD & Supply Chain

- **Automated Workflows**: GitHub Actions CI (`ci.yml`), release packaging (`release.yml`), container scans (`container.yml`), and Dependabot (`dependabot.yml`).
- **Wheel Smoke Test**: Automatic wheel package build and virtual environment smoke test on every build.
- **Image Pinning**: Zero `:latest` tags. Pinned vendor versions (`prom/prometheus:v2.54.1`, `grafana/loki:3.1.1`, `grafana/alloy:v1.3.1`, `grafana/grafana:11.2.0`).

---

## Removed Components

| Removed Component | Replacement / Reason |
| :--- | :--- |
| `src/fritz_monitoring/avm/` | Replaced by `fritz-avm-client>=0.2.0` |
| `mesh_discovery` container & `Dockerfile.discovery` | Replaced by single `fritz-exporter:8000` target |
| `promtail` container & `promtail-config.yml` | Replaced by Grafana Alloy Syslog UDP listener |
| `log_pusher` container & `Dockerfile.log_pusher` | Removed duplicate log polling pipeline |
| Infinity Datasource (`infinity.yml`) | Removed unused Grafana plugin dependency |

---

## Remaining Risks & Mitigations

| Risk | Mitigation / Operational Note |
| :--- | :--- |
| Single-Node Loki Filesystem Storage | Documented single point of failure in `BACKUP_RESTORE.md`. S3-compatible storage migration path provided for enterprise scale. |
| Temporary FRITZ!Box Reboot / Disconnection | Exporter returns HTTP 200 `/healthz` and HTTP 503 `/readyz` while reporting `fritz_scrape_success=0`. Scrape metrics do not convert timeouts into fake zero values. |

---

## Test Evidence & Verification Results

### 1. `fritz-avm-client` Unit & Contract Test Suite

```text
================= 24 passed, 2 skipped in 0.37s ==================
Coverage: 80% (src/fritz_avm_client)
Wheel package build & smoke test: PASS
```

### 2. `fritz.box-monitoring` Test Suite

```text
================= 8 passed in 0.27s ==================
Coverage: 69% (src/fritz_monitoring)
```

### 3. Docker Compose Production Configuration Validation

```bash
$ docker compose -f compose.prod.yml config
Exit code: 0 (Validated successfully)
```

---

## Production Deployment Command

To deploy the production stack:

```bash
docker compose --env-file .env.production -f compose.prod.yml up -d
```
