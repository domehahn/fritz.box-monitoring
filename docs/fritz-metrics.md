# FRITZ!Box Metric Catalogue

Every `fritz_*` series exposed by `fritz-exporter`, plus the `fritz:*` recording
rules. Source classification:

* **AVAILABLE** — read directly from a FRITZ!Box interface today.
* **DERIVED** — computed by exporter or Prometheus from AVAILABLE inputs.
* **REQUIRES_NEW_COLLECTOR** — the data exists on a FRITZ! interface but the
  current exporter/`fritz-avm-client` does not surface it.
* **NOT_AVAILABLE** — not exposed reliably by FRITZ!OS on the target hardware.

Live totals: ~177 series. `changes`/`ip`/`name` labels churn a little on DHCP
renewals and device renames; negligible at this fleet size.

---

## Collector self-metrics — AVAILABLE (from the exporter itself)

| Metric | Type | Unit | Labels | Meaning |
| --- | --- | --- | --- | --- |
| `fritz_scrape_success` | gauge | bool | — | 1 if the last collection pass succeeded |
| `fritz_scrape_duration_seconds` | gauge | s | — | Wall time of the last collection pass (~25 s here) |
| `fritz_scrape_errors_total` | counter | — | `type` | Collection errors by class (`timeout`, `authentication_error`, …) |
| `fritz_consecutive_scrape_failures` | gauge | — | — | Consecutive failed passes |
| `fritz_snapshot_age_seconds` | gauge | s | — | Age of the snapshot currently served |
| `fritz_last_success_timestamp_seconds` | gauge | unix s | — | Time of last successful pass |
| `fritz_exporter_build_info` | gauge | — | `version` | Always 1; version carried as label |
| `fritz_capability_available` | gauge | bool | `feature` | 1 if the FRITZ!Box exposes `mesh_topology` / `wlan_associations` / `device_log` to the monitoring account. `0` on a least-privilege account → see [fritz-permissions.md](fritz-permissions.md). Probed once at startup |

## WAN — AVAILABLE (`fritz-avm-client` → `fritzconnection` FritzStatus)

| Metric | Type | Unit | Labels | Meaning |
| --- | --- | --- | --- | --- |
| `fritz_router_is_connected` | gauge | bool | — | WAN link established |
| `fritz_router_connection_uptime_seconds` | gauge | s | — | Since last PPP/DHCP (re)connect |
| `fritz_router_uptime_seconds` | gauge | s | — | Device uptime |
| `fritz_router_current_bytes_received_rate` | gauge | **bytes/s** | — | Instantaneous WAN download rate |
| `fritz_router_current_bytes_sent_rate` | gauge | **bytes/s** | — | Instantaneous WAN upload rate |
| `fritz_router_max_byte_rate_down` | gauge | **bytes/s** | — | Negotiated downstream line capacity |
| `fritz_router_max_byte_rate_up` | gauge | **bytes/s** | — | Negotiated upstream line capacity |
| `fritz_router_bytes_received_total` | gauge (⚠ not counter) | bytes | — | Cumulative WAN RX; **resets on reconnect/reboot** — do not `rate()` |
| `fritz_router_bytes_sent_total` | gauge (⚠ not counter) | bytes | — | Cumulative WAN TX; same caveat |
| `fritz_router_external_ip` | gauge (info) | — | `ip` | Current public IP as label, value 1 |

## DSL line quality — AVAILABLE

| Metric | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `fritz_router_dsl_downstream_attenuation` | gauge | dB | Downstream attenuation |
| `fritz_router_dsl_upstream_attenuation` | gauge | dB | Upstream attenuation |
| `fritz_router_dsl_downstream_noise_margin` | gauge | dB | Downstream SNR margin |
| `fritz_router_dsl_upstream_noise_margin` | gauge | dB | Upstream SNR margin |

## System — AVAILABLE

| Metric | Type | Unit | Labels | Meaning |
| --- | --- | --- | --- | --- |
| `fritz_router_cpu_temperature_celsius` | gauge | °C | `cpu` | Per-core CPU temperature (label cleared each render) |

## Devices, aggregate — AVAILABLE

| Metric | Type | Meaning |
| --- | --- | --- |
| `fritz_total_devices` | gauge | Known hosts in the FRITZ!Box host list |
| `fritz_online_devices` | gauge | Currently active hosts |
| `fritz_offline_devices` | gauge | `total - online` (DERIVED) |

## Devices, per client

| Metric | Type | Unit | Labels | Source | Meaning |
| --- | --- | --- | --- | --- | --- |
| `fritz_device_up` | gauge | bool | `mac`, `name`, `ip`, `node`, `node_mac`, `interface`, `repeater`, `powerline` | AVAILABLE | Client reachable. **State metric — not an event log.** `node` currently always `fritz.box` (see below) |
| `fritz_device_rx_bytes_total` | gauge | bytes | same | AVAILABLE | Per-client cumulative RX (resets like WAN) |
| `fritz_device_tx_bytes_total` | gauge | bytes | same | AVAILABLE | Per-client cumulative TX |
| `fritz_device_wlan_signal_strength` | gauge | % (0–100) | `mac`, `name`, `ip`, `node`, `node_mac` | AVAILABLE | Per-client Wi-Fi signal. Populated once the account has "FRITZ!Box Einstellungen" (needs `collector._patch_client_quirks` — `get_wlan_devices()` returns `signal`, not `signal_strength`) |
| `fritz_device_wlan_speed_mbps` | gauge | Mbit/s | same | AVAILABLE | PHY/negotiated rate; same path |

> **Per-client → access-point attribution.** Working once the account has the
> "FRITZ!Box Einstellungen" permission — `fritz_device_up{node=…}` then shows the
> real repeater/powerline. `ap_mac` from the WLAN association list is not exposed
> by `get_wlan_devices()`, so attribution comes from the mesh JSON path instead.

## WLAN, aggregate — AVAILABLE

| Metric | Type | Meaning |
| --- | --- | --- |
| `fritz_wlan_packets_sent_total` | gauge | Sum of per-band TX packet counters |
| `fritz_wlan_packets_received_total` | gauge | Sum of per-band RX packet counters |

## Mesh infrastructure

| Metric | Type | Unit | Labels | Source | Meaning |
| --- | --- | --- | --- | --- | --- |
| `fritz_node_up` | gauge | bool | `name`, `mac`, `type` | AVAILABLE | Node active in the mesh. Goes **stale** (no samples), not →0, if a node leaves the mesh list entirely |
| `fritz_node_info` | gauge (info) | — | `name`, `mac`, `type`, `model`, `ip`, `parent_name` | AVAILABLE | Node metadata, value 1 |
| `fritz_node_link_rx_kbps` | gauge | kbit/s | `name`, `mac`, `type` | AVAILABLE | Current node uplink RX speed (backhaul-ish; aggregate of node interface links) |
| `fritz_node_link_tx_kbps` | gauge | kbit/s | `name`, `mac`, `type` | AVAILABLE | Current node uplink TX speed |
| `fritz_repeater_connected_devices` | gauge | count | `name`, `mac` | DERIVED | Clients whose `connected_to` matches this repeater. **Reads 0 everywhere** while per-client attribution is unresolved |
| `fritz_powerline_connected_devices` | gauge | count | `name`, `mac` | DERIVED | As above for Powerline nodes |
| `fritz_node_parent` | gauge | — | `name`, `mac`, `parent_name`, `parent_mac` | DERIVED | Mesh parent edge, value 1. **Live** (real parent/child links) once the account has "FRITZ!Box Einstellungen". Drives the `fritz_mesh` hierarchy table + Node Graph edges |

### Backhaul detail — REQUIRES_NEW_COLLECTOR / partially NOT_AVAILABLE

Backhaul **type** (Wi-Fi 2.4/5 GHz vs Powerline vs Ethernet), negotiated
**band/channel/width**, and per-link RX/TX split are present in the mesh JSON
(`node_interfaces[].node_links[].cur_data_rate_rx/tx`, interface `type`) but are
currently aggregated away into `fritz_node_link_*_kbps`. Exposing them cleanly
needs a collector change. FRITZ!OS does expose the raw values.

---

## Recording rules — DERIVED (added this iteration)

| Rule | Expr (summary) | Unit |
| --- | --- | --- |
| `fritz:wan_download_throughput_bytes:rate` | `fritz_router_current_bytes_received_rate` | bytes/s |
| `fritz:wan_upload_throughput_bytes:rate` | `fritz_router_current_bytes_sent_rate` | bytes/s |
| `fritz:wan_download_utilization:ratio` | `… / (fritz_router_max_byte_rate_down > 0)` | ratio 0–1 |
| `fritz:wan_upload_utilization:ratio` | `… / (fritz_router_max_byte_rate_up > 0)` | ratio 0–1 |
| `fritz:device_connection_changes:1h` | `changes(fritz_device_up[1h])` | edges (flap = 2) |
| `fritz:device_connection_changes:24h` | `changes(fritz_device_up[24h])` | edges |
| `fritz:node_connection_changes:24h` | `changes(fritz_node_up[24h])` | edges |
| `fritz:mesh_nodes_healthy:count` | `count(fritz_node_up == 1) or vector(0)` | count |
| `fritz:mesh_nodes_total:count` | `count(fritz_node_up) or vector(0)` | count |
| `fritz:node_link_rx_kbps:max24h` / `:tx_…` | `max_over_time(fritz_node_link_*_kbps[24h])` | kbit/s — per-node backhaul baseline |
| `fritz:node_backhaul_health:ratio` | current link rate ÷ 24h baseline, min(rx,tx) | 0–1; **0 series in practice** — `fritz_node_link_*_kbps` reads 0 on the test box, so no baseline (graceful: no garbage) |
| `fritz:node_health:code` | `4`=OFFLINE, `1/2/3`=HEALTHY/DEGRADED/CRITICAL from `fritz_node_up` + flaps/24h (≥3 → DEGRADED, ≥8 → CRITICAL) | code; label→colour mapping applied in the Grafana table |

---

## Blackbox probe metrics — AVAILABLE (Blackbox Exporter, added)

`probe_*` series carry `job` (`probe_icmp_infra` / `probe_icmp_internet` /
`probe_dns_local` / `probe_dns_external`), `instance` (target), `probe_kind`, and
`hop` / `resolver` from `config/blackbox/targets/*.yml`.

| Metric / rule | Meaning |
| --- | --- |
| `probe_success` | probe succeeded this scrape (1/0) |
| `probe_icmp_duration_seconds{phase="rtt"}` | ICMP round-trip time |
| `probe_dns_lookup_time_seconds` | DNS query time |
| `fritz:probe_rtt_seconds` / `:p95_10m` | RTT and 10 m p95 |
| `fritz:probe_loss_ratio:5m` | `1 - avg_over_time(probe_success[5m])` — failed-scrape fraction, **not** per-packet loss |
| `fritz:probe_jitter_seconds:10m` | `stddev_over_time(probe_icmp_duration_seconds{phase="rtt"}[10m])` — RTT variation |
| `fritz:dns_lookup_seconds:p95_10m`, `fritz:dns_success_ratio:5m` | DNS latency / success rate |

## iperf3 LAN reference — opt-in (`--profile iperf`, see [iperf-reference.md](iperf-reference.md))

| Metric | Meaning |
| --- | --- |
| `iperf_enabled` | 1 if `IPERF_TARGET` set |
| `iperf_last_run_success` / `iperf_last_run_timestamp_seconds` | last test outcome / time |
| `iperf_sent_bits_per_second` / `iperf_received_bits_per_second` | upload / download throughput |
| `iperf_retransmits` | TCP retransmits, last test |

## FRITZ!Box account permission (`fritz_capability_available`)

The exporter probes 3 permission-gated actions at startup and exposes
`fritz_capability_available{feature}` (1 = usable). **This deployment's
`Monitoring` user has "FRITZ!Box Einstellungen" → all three are `1`** and the
features below are live:

| Feature | Action | Now provides |
| --- | --- | --- |
| `mesh_topology` | `Hosts1:X_AVM-DE_GetMeshListPath` | `fritz_node_parent` edges, `fritz_node_link_*_kbps` > 0, per-client `fritz_device_up{node=<repeater>}`, `fritz_repeater_connected_devices` |
| `wlan_associations` | `WLANConfiguration*:GetGenericAssociatedDeviceInfo` | `fritz_device_wlan_signal_strength` / `_speed_mbps` per client |
| `device_log` | `DeviceInfo1:GetDeviceLog` | available (not yet wired into the event pipeline — snapshot-derived events cover the essentials) |

`FritzCapabilityMissing` alerts if any drops to 0 (e.g. permission revoked).
`collector._patch_client_quirks` works around two `fritz-avm-client` 0.3.0 bugs
that only surface once this data flows.

## Genuinely needs new components

| Wanted | Path |
| --- | --- |
| LAN vs WAN throughput reference | opt-in iperf3 job (P3) |
