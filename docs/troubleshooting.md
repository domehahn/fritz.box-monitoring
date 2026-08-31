# Troubleshooting Playbook

Practical scenarios for the FRITZ!Box NOC. Dashboards referenced by UID; open
via `http://127.0.0.1:3000/d/<uid>`.

## "The internet is slow"

1. **Home Network NOC (`fritz_noc`) → Health row.**
   * `WAN` = CONNECTED? If not → WAN/ISP outage, stop here.
   * `Download util` / `Upload util`. Upload ≥90 % (red) with a small uplink is
     the most common cause — a single upload (cloud backup, video call, game
     patch seeding) starves everything. Check **WAN throughput vs capacity** to
     see which direction and how long.
2. If utilisation is low, split LAN vs WAN vs DNS on **Network Path Probes
   (`fritz_probes`)**:
   * WAN RTT p95 / packet loss high while gateway RTT is fine → ISP/line issue.
   * Gateway (or a repeater) RTT / loss high → local infrastructure.
   * Both RTTs fine but **DNS lookup p95** high or `DNS local/external OK` red →
     resolver problem, not the network ("network healthy but DNS slow").
3. If the path looks clean, the bottleneck is **Wi-Fi / client**:
   * **NOC Stability section** → any mesh node red on the state timeline during
     the complaint window? A flapping repeater degrades everything behind it.
   * "Most unstable clients (24h)" — is the affected device in the list?
4. **Client Diagnostics (`fritz_client`)**, pick `$device`:
   * Connection-state timeline — disconnects during the window?
   * Access-point-over-time — did it bounce between nodes (roaming)?
   * Wi-Fi signal / PHY rate — a drop from hundreds of Mbit/s to tens indicates
     a poor radio path (distance, interference, band steering). *These panels
     are empty until the collector surfaces per-client WLAN stats — see
     [fritz-metrics.md](fritz-metrics.md).*
5. **Correlate.** With the "mesh node down" annotation on, check whether a node
   event lines up with the throughput dip.
6. **Conclusion rule:** WAN utilisation normal + local Wi-Fi/AP anomaly present
   → local problem, not the ISP. WAN utilisation pinned → capacity/ISP problem.
   Do **not** state a root cause the panels don't support.

## "A specific device keeps dropping"

1. `fritz_noc` → "Most unstable clients (24h)" and (1h) flap count.
2. `fritz_client` with that `$device` → connection-state timeline for the shape
   (regular interval = power save / driver; random = RF).
3. Check `FritzExcessiveClientReconnects` in Alertmanager/Grafana alerts.

## "A repeater looks unhealthy"

1. `fritz_noc` → mesh node state timeline; `fritz_mesh_devices` → node table for
   parent, model, IP.
2. `fritz_node_link_rx_kbps` / `_tx_kbps` for that node — a backhaul that
   negotiated far below its siblings is a slow-chain candidate.
3. `FritzExcessiveNodeReconnects` / `FritzMeshNodeDown`.
4. Full per-repeater latency/loss and a HEALTHY/DEGRADED verdict need the
   Blackbox probes (not yet deployed).

## Collector / exporter problems

| Symptom | Check | Likely cause |
| --- | --- | --- |
| All `fritz_*` gauges flatline | `fritz_scrape_success`, exporter logs | wrong FRITZ credentials, box unreachable, TR-064 disabled |
| `fritz_snapshot_age_seconds` climbing | `fritz_scrape_duration_seconds`, `fritz_consecutive_scrape_failures` | box slow/overloaded, transient TR-064 timeouts |
| Prometheus target down | `docker logs fritz-monitoring-prod-fritz-exporter-1` | container crash / port |
| Recording rule `unknown` health | Prometheus → Status → Rules | wait one eval interval; then check expression |

Credentials live in `secrets/fritz_password.txt` (prod) / `.env` (dev). After a
FRITZ!Box password change, update the secret and
`docker compose -f compose.prod.yml up -d --force-recreate fritz-exporter`.

## Validating config changes

```bash
docker exec fritz-monitoring-prod-prometheus-1 promtool check config /etc/prometheus/prometheus.yml
docker exec fritz-monitoring-prod-prometheus-1 promtool check rules /etc/prometheus/rules/*.yml
docker compose -f compose.prod.yml config -q
poetry run pytest -q && poetry run ruff check src tests && poetry run mypy src
```

Dashboards reload from disk within ~10 s (`updateIntervalSeconds: 10`). Confirm:

```bash
curl -s "http://admin:$PW@127.0.0.1:3000/api/dashboards/uid/fritz_noc" | jq '.dashboard.title'
```
