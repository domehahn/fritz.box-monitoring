# Network Observability — Current State & Gap Analysis

Snapshot of the monitoring stack as of the NOC v4 work. Written from a live
inspection of the running production stack, the exporter source, and the
`fritz-avm-client` 0.3.0 package it depends on.

## 1. Architecture

```text
FRITZ!Box 7590 (192.168.178.1, TR-064 :49000)
        │  TR-064 / FritzStatus / mesh JSON / WLAN assoc list
        ▼
fritz-exporter  (src/fritz_monitoring/)
  ├─ collector.py            background thread, 30s interval, atomic snapshot swap
  │    └─ fritz_avm_client.FritzClient
  │         ├─ get_wan_stats_typed()          WAN throughput / capacity / uptime
  │         ├─ router_client.get_dsl_stats()  DSL attenuation / noise margin
  │         ├─ wlan_client.get_wlan_stats()   per-band packet counters (aggregated)
  │         └─ discover_mesh()                nodes + client devices + link speeds
  ├─ exporter/prometheus_exporter.py  snapshot -> Prometheus text
  └─ exporter/server.py               aiohttp :8000  /metrics /healthz /readyz
        ▼
Prometheus v2.54.1  (30s scrape, 30d retention)
  └─ rules/  fritz_alerts.yml, fritz_recording_rules.yml
        ▼
Grafana 11.5.0  (provisioned datasources + dashboards)

Loki 3.1.1  ← Alloy v1.3.1  (RFC3164 syslog :1514/udp + Docker container logs)
Device Manager (Flask, profile: admin)  read + host-deletion UI
```

All service-to-service traffic is on an internal Docker network; only Grafana
(127.0.0.1:3000), the syslog listener and the Device Manager (127.0.0.1:5000)
are published, all loopback-bound.

## 2. Existing `fritz_*` metrics (live inventory)

39 metric families, **~177 series total** — cardinality is a non-issue at this
scale. Full catalogue with labels/units/source in [fritz-metrics.md](fritz-metrics.md).

| Area | Metrics |
| --- | --- |
| Collector health | `fritz_scrape_success`, `fritz_scrape_duration_seconds`, `fritz_scrape_errors_total`, `fritz_consecutive_scrape_failures`, `fritz_snapshot_age_seconds`, `fritz_last_success_timestamp_seconds`, `fritz_exporter_build_info` |
| WAN | `fritz_router_is_connected`, `fritz_router_connection_uptime_seconds`, `fritz_router_uptime_seconds`, `fritz_router_bytes_received_total`, `fritz_router_bytes_sent_total`, `fritz_router_current_bytes_received_rate`, `fritz_router_current_bytes_sent_rate`, `fritz_router_max_byte_rate_down`, `fritz_router_max_byte_rate_up`, `fritz_router_external_ip` |
| DSL | `fritz_router_dsl_downstream_attenuation`, `fritz_router_dsl_upstream_attenuation`, `fritz_router_dsl_downstream_noise_margin`, `fritz_router_dsl_upstream_noise_margin` |
| System | `fritz_router_cpu_temperature_celsius` |
| Devices (aggregate) | `fritz_total_devices`, `fritz_online_devices`, `fritz_offline_devices` |
| Devices (per client) | `fritz_device_up`, `fritz_device_rx_bytes_total`, `fritz_device_tx_bytes_total`, `fritz_device_wlan_signal_strength`, `fritz_device_wlan_speed_mbps` |
| WLAN (aggregate) | `fritz_wlan_packets_sent_total`, `fritz_wlan_packets_received_total` |
| Mesh nodes | `fritz_node_up`, `fritz_node_info`, `fritz_node_link_rx_kbps`, `fritz_node_link_tx_kbps`, `fritz_repeater_connected_devices`, `fritz_powerline_connected_devices`, `fritz_node_parent` |

### Unit facts (verified)

* `fritz_router_current_bytes_*_rate` and `fritz_router_max_byte_rate_*` are
  **bytes/s** (`fritzconnection` `FritzStatus.transmission_rate` / `.max_byte_rate`,
  both already divided by 8). Multiply by 8 only for bit/s display.
* `fritz_router_bytes_*_total` are **bytes**, but exposed as a **gauge** that
  **resets on WAN reconnect/reboot** → `rate()` on them is wrong. Throughput must
  come from the `*_rate` gauges. The old "network utilization" panel used
  `rate(..._total[5m])` and summed up+down into one figure — both bugs.
* `fritz_node_link_*_kbps` are **kbit/s**.
* `*_total` naming on gauges (`fritz_router_bytes_*_total`,
  `fritz_device_*_bytes_total`) is misleading but left as-is for compatibility.

## 3. Dashboards before this change

| UID | Title | Notes |
| --- | --- | --- |
| `fritz_overview` | Fritz!Box System Overview | 10 panels, **no template vars**; "Real-time Internet Traffic" mixes 4 series; no independent up/down utilisation |
| `fritz_mesh_devices` | Fritz!Box Mesh & Devices | `$node`, `$interface` vars; node table + client inventory |
| `fritz_logs` | Fritz!Box System Logs | Loki; `$search` var |
| `fritz_home` | FritzBox Home Overview | restored hand-built dashboard, 27 panels, some redundancy with mesh_devices; contained a **hard-coded Mermaid topology** |

Duplication observed across `fritz_home` / `fritz_mesh_devices`: "Devices per
Repeater", "Repeater Device Counts", "Devices per Repeater (stat)", "Connected
Devices per Access Point", "All Connected Devices", "Device Status Overview",
"Online/Offline Devices" — five+ variations of the same inventory.

## 4. Gaps vs. a real NOC

| Capability | Status | Blocker |
| --- | --- | --- |
| Independent WAN down/up throughput + utilisation | **fixed here** (recording rules + NOC dashboard) | — |
| Dashboard template variables (`$device` etc.) | **added** (Client Diagnostics) | — |
| State-timeline views instead of 0/1 line graphs | **added** (NOC) | — |
| Connection-flap statistics (`changes()`) | **added** (recording rules + NOC panels) | — |
| Active latency / packet loss to gateway, WAN, DNS | **done** — Blackbox Exporter + `fritz_probes` dashboard + probe alerts | — |
| Local vs external DNS resolution time | **done** — `probe_dns_local` / `probe_dns_external` | — |
| Repeater Health Matrix (derived HEALTHY/DEGRADED/…) | **done** — `fritz_mesh` dashboard, verdict from `fritz:node_health:code` (up + flaps/24h) | backhaul link rates now populate (`fritz_node_link_*_kbps` > 0) so the degradation column works; per-repeater latency/loss still needs their IPs in `icmp_infra.yml` |
| Per-client AP attribution, Wi-Fi signal/PHY, roaming, mesh topology edges, per-repeater backhaul | **WORKING** — monitoring user got "FRITZ!Box Einstellungen"; `fritz_capability_available` = 1/1/1 | Live: real `fritz_node_parent` edges, `fritz_node_link_*_kbps` > 0, `fritz_device_wlan_signal_strength` populated, `fritz_device_up{node=…}` shows real repeaters. Two `fritz-avm-client` 0.3.0 bugs worked around in `collector._patch_client_quirks` |
| Active latency / packet loss (gateway, WAN anchors, DNS) | **done** (Blackbox Exporter) | per-repeater needs their IPs added to `config/blackbox/targets/icmp_infra.yml` |
| Jitter | **done** — `fritz:probe_jitter_seconds:10m`, panel on `fritz_probes`, `FritzHighJitter` alert | — |
| LAN-vs-WAN throughput reference | **done (opt-in)** — `iperf-probe` compose profile + `iperf_*` metrics + panel, disabled by default, interval-floored | needs a wired LAN host running `iperf3 -s`; see [iperf-reference.md](iperf-reference.md) |
| Structured event pipeline (connect/disconnect/WAN/reboot/parent-change) | **done, end-to-end** — snapshot-diff events → JSON logs → Loki → `fritz_events` + NOC annotation, verified through Grafana | see [event-pipeline.md](event-pipeline.md) |
| Alloy → Loki log delivery (also blocked `fritz_logs`) | **fixed** — `discovery.docker` was unscoped and emitting per-port duplicate targets; added `discovery.relabel` to scope to this compose project. `loki_write_sent_entries_total > 0` | — |
| Roaming / channel-change / auth-failure events | not derivable | roaming needs per-client AP attribution; rest need the device log (401) |
| Dynamic graphical topology | **done** — `fritz_mesh` Node Graph (nodes `fritz_node_info`, edges `fritz_node_parent`) + hierarchy table, replacing the hard-coded Mermaid | edges are live (6 real parent/child links) |
| iperf3 LAN reference | **done (opt-in)** — see row above | — |

## 5. What changed in this iteration (P0 tier)

* `config/prometheus/rules/fritz_recording_rules.yml` — correct, independent
  `fritz:wan_download_utilization:ratio` / `fritz:wan_upload_utilization:ratio`,
  throughput passthroughs, `fritz:device_connection_changes:1h|24h`,
  `fritz:node_connection_changes:24h`, healthy/total node counts.
* `config/prometheus/rules/fritz_alerts.yml` — added `fritz_network_alerts`
  group: `FritzMeshNodeDown`, `FritzWanDownloadSaturated`,
  `FritzWanUploadSaturated`, `FritzExcessiveClientReconnects`,
  `FritzExcessiveNodeReconnects`.
* `config/grafana/provisioning/dashboards_files/noc.json` — **Home Network NOC**
  (`fritz_noc`): health KPIs, independent WAN down/up throughput vs capacity and
  utilisation, mesh-node state timeline, unstable-clients / unstable-nodes
  tables, flapped-clients state timeline, "mesh node down" annotation.
* `config/grafana/provisioning/dashboards_files/client.json` — **Client
  Diagnostics** (`fritz_client`) with mandatory `$device` plus `$node` / `$type`
  query variables; connection-state timeline, AP-over-time, Wi-Fi signal / PHY
  (render when FRITZ!OS exposes them), per-device throughput.
* Dedup (Phase 23): `fritz_overview` retired (fully covered by `fritz_noc`);
  `fritz_mesh_devices` rescoped to **Client Inventory** (detailed per-client
  table only). `fritz_logs` and the user's `fritz_home` left untouched.

## 6. Added after P0 (P1 — active probing)

* New service `blackbox-exporter` (`quay.io/prometheus/blackbox-exporter:v0.25.0`,
  `cap_drop: ALL` + `cap_add: NET_RAW`) in `compose.prod.yml` and
  `compose.dev.yml`.
* `config/blackbox/blackbox.yml` — `icmp`, `icmp_lan`, `dns_a`, `http_2xx`
  modules.
* `config/blackbox/targets/*.yml` — Prometheus `file_sd`, hot-reloaded: FRITZ!Box
  + public anchors + local/external resolvers; add repeater IPs here.
* `config/prometheus.yml` — 4 probe scrape jobs + blackbox self-scrape, standard
  `__param_target` relabel; `--web.enable-lifecycle` enabled.
* `config/prometheus/rules/probe_rules.yml` — 6 recording rules
  (`fritz:probe_rtt_seconds`, `:p95_10m`, `fritz:probe_loss_ratio:5m`,
  `fritz:dns_lookup_seconds*`, `fritz:dns_success_ratio:5m`) + 9 alerts
  (gateway/WAN latency warn+crit, packet loss warn+crit, probe down, DNS
  slow/failing).
* `config/grafana/provisioning/dashboards_files/probes.json` — **Network Path
  Probes** (`fritz_probes`).

See [dashboards.md](dashboards.md) and [troubleshooting.md](troubleshooting.md).
