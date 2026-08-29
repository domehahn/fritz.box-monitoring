# Migration Guide - Upgrading from Prototype to Production

## Summary of Architectural Changes

1. **Client SDK Unification**: Removed `src/fritz_monitoring/avm/` embedded client code and direct `fritzconnection` dependency. All AVM TR-064 calls are executed via `fritz-avm-client>=0.2.0`.
2. **Prometheus Scraping Architecture**: Removed direct TR-064 port `49000` scraping and `mesh_discovery` sidecar container. Prometheus now scrapes a single target (`fritz-exporter:8000`).
3. **Background Snapshot Collector**: Replaced synchronous scrape-time TR-064 queries with an asynchronous background collector loop (`CollectorService`). `/metrics` serves the latest atomic snapshot.
4. **Log Ingestion Overhaul**: Removed `promtail` and `log_pusher`. Logs are ingested directly via FRITZ!Box Syslog UDP (port 1514) into `Grafana Alloy`, forwarded to `Loki` (persisted under `/loki`).
5. **Device Manager Hardening**: Disabled by default (Compose profile `admin`), equipped with HTTP Basic/Session auth, CSRF protection, strict MAC address regex validation, and Gunicorn WSGI.

---

## Migration Steps for Existing Deployments

1. Stop legacy container stack:

   ```bash
   docker compose down -v
   ```

2. Remove obsolete container images and volumes:

   ```bash
   docker volume rm fritz-monitoring_prometheus_targets
   ```

3. Configure file-based secrets under `secrets/`:

   ```bash
   mkdir -p secrets
   echo "your_fritz_password" > secrets/fritz_password.txt
   echo "your_grafana_password" > secrets/grafana_admin_password.txt
   echo "your_device_manager_password" > secrets/device_manager_admin_password.txt
   ```

4. Launch production stack:

   ```bash
   docker compose --env-file .env.production -f compose.prod.yml up -d
   ```
