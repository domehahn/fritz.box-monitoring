# Grafana Dashboards

All dashboards are provisioned from
`config/grafana/provisioning/dashboards_files/` (folder **FritzBox**) and use the
`prometheus` / `loki` datasource UIDs.

| UID | Title | Role |
| --- | --- | --- |
| `fritz_noc` | **Home Network NOC** | First screen when "the internet is slow". Is something wrong, what, where, since when |
| `fritz_client` | **Client Diagnostics** | Deep-dive on one device (`$device`) |
| `fritz_probes` | **Network Path Probes** | Active ICMP / DNS latency & loss per hop (LAN → WAN → DNS) |
| `fritz_events` | **Network Events & Forensics** | Derived connect/disconnect/WAN/reboot events (Loki) — see [event-pipeline.md](event-pipeline.md) |
| `fritz_mesh` | **Mesh Infrastructure** | Repeater Health Matrix, hierarchy, live topology graph, node state timeline, backhaul |

The legacy `fritz_overview`, `fritz_mesh_devices`, `fritz_logs` and
`fritz_home` dashboards were retired once these five cover everything with live
data. Raw log search is available via Grafana **Explore** on the `loki`
datasource.

## Home Network NOC (`fritz_noc`)

Sections top to bottom: **Health → WAN utilisation → Stability**.

* **Health row** — WAN state, download & upload throughput (bit/s), independent
  download & upload utilisation (green <80 %, orange ≥80 %, red ≥95 %), clients
  online, flapping clients in the last hour, healthy/problem mesh nodes,
  collector health, snapshot age.
* **WAN utilisation** — throughput vs negotiated line capacity, and the two
  utilisation ratios on one axis. Upload and download are **never summed** — a
  saturated 50 Mbit uplink is the usual cause of "everything is slow" and must
  be visible on its own.
* **Stability** — mesh-node state timeline; "most unstable clients / nodes (24h)"
  tables from `changes()`; a state timeline restricted to clients that actually
  flapped in the last 24h (so it stays readable with ~90 clients).
* **Annotation** — "mesh node down" (`fritz_node_up == 0`) overlays on every
  time panel for correlation.

## Client Diagnostics (`fritz_client`)

Variables: **`$device`** (single-select, required), `$node`, `$type` — all
`label_values(...)` queries, so they follow the fleet automatically.

Panels: current state / AP / interface / IP / flap counts (1h, 24h);
connection-state timeline; access-point-over-time; Wi-Fi signal and PHY rate
(populate only once the collector surfaces per-client WLAN stats — see
[fritz-metrics.md](fritz-metrics.md)); per-device throughput (bit/s) from the
byte gauges.

Use it to investigate statements like *"the iPhone was slow at 20:41"*: line up
the connection-state, AP and (when available) signal/PHY panels on the same time
window.

## Mesh Infrastructure (`fritz_mesh`)

Detailed FRITZ!Box / Repeater / Powerline diagnostics.

**FRITZ!Box data access row** — three stats from `fritz_capability_available`
(`mesh_topology` / `wlan_associations` / `device_log`). Currently all **available**
(the `Monitoring` user has "FRITZ!Box Einstellungen"). If one flips to "WITHHELD"
the panels below it degrade — [fritz-permissions.md](fritz-permissions.md) has the
fix. The NOC Health row carries a compact "FULL / LIMITED" mirror.

**Repeater Health Matrix** — one row per mesh node: parent, up, **Health**
verdict, flaps/24h, backhaul RX/TX kbit/s, client count, backhaul-health ratio.
Built by merging seven instant queries on the shared `{name,mac,type}` label
set; `fritz_node_info` supplies the descriptive columns.

Health algorithm (`fritz:node_health:code`, colour applied via table value
mappings), using **only metrics available today**:

| Code | Label | Condition |
| --- | --- | --- |
| 4 | OFFLINE | `fritz_node_up == 0` |
| 3 | CRITICAL | node up and `fritz:node_connection_changes:24h >= 8` |
| 2 | DEGRADED | node up and `>= 3` flaps/24h |
| 1 | HEALTHY | node up, `< 3` flaps/24h |

Backhaul degradation (`fritz:node_backhaul_health:ratio` = current link rate ÷
its own 24h peak) is wired into the matrix and a trend panel, but
`fritz_node_link_*_kbps` currently reads 0 on the test hardware, so that column
stays empty — it is not folded into the Health verdict until real data appears.
Per-repeater **latency / packet loss** and a fuller verdict need each repeater's
IP added to `config/blackbox/targets/icmp_infra.yml`.

**Live topology** — a Grafana **Node Graph** built from two Prometheus frames:
nodes from `fritz_node_info` (`label_replace` → `id`/`title`/`mainStat`), edges
from `fritz_node_parent` (`label_join` → `id`/`source`/`target`). It rebuilds
itself when a repeater is added/removed or a parent changes — no hard-coded
diagram.

> Edges are **live** — `fritz_node_parent` carries the real parent/child links
> (6 on this box). Requires the `mesh_topology` capability (see above) plus the
> two `fritz-avm-client` 0.3.0 workarounds in `collector._patch_client_quirks`.

Also: mesh hierarchy table (from `fritz_node_parent`), node state timeline,
most-unstable-nodes ranking, link-rate trend.

## Network Path Probes (`fritz_probes`)

Fed by the **Blackbox Exporter** service (`config/blackbox/`). Models the path
`LAN infra → WAN → DNS` so a slow-network complaint can be attributed:

* **Reachability row** — LAN infra / internet reachable %, DNS local & external OK.
* **Latency** — per-hop ICMP RTT, LAN vs internet side by side.
* **Packet loss** — `1 - avg_over_time(probe_success[5m])` per hop (blackbox
  sends one echo per scrape, so this is failed-scrape fraction, ~5 % resolution
  at 15 s scrape / 5 m window — not per-packet loss).
* **DNS** — local vs external resolver lookup time; path summary table.
* **Jitter** — RTT stddev over 10 m per hop (`fritz:probe_jitter_seconds:10m`);
  `FritzHighJitter` alerts above 10 ms.
* **iperf3 LAN reference** — throughput from the opt-in probe (empty unless
  `--profile iperf` + `IPERF_TARGET`; see [iperf-reference.md](iperf-reference.md)).

### Probe targets

`config/blackbox/targets/*.yml` (Prometheus `file_sd`, hot-reloaded ~30 s, no
restart). Ships with the FRITZ!Box (`192.168.178.1`) and public anchors
(`1.1.1.1`, `8.8.8.8`, `9.9.9.9`). **Add your repeater / powerline IPs** to
`icmp_infra.yml` to get per-repeater latency and loss.

> ICMP RTT from a container on Docker Desktop (macOS/Windows) is not
> representative — the VM NAT collapses it to sub-millisecond. On a Linux host
> with the container on a bridge that routes to the LAN the values are real.

## Recording rules & alerts

`config/prometheus/rules/fritz_recording_rules.yml` and `fritz_alerts.yml`.

Alert thresholds (starting points — tune per line):

| Alert | Condition | For | Sev | Rationale |
| --- | --- | --- | --- | --- |
| `FritzExporterDown` | `up{job="fritz"} == 0` | 2m | crit | scrape target unreachable |
| `FritzScrapeFailed` | `fritz_scrape_success == 0` | 5m | warn | collector can't reach the box |
| `FritzSnapshotStale` | `fritz_snapshot_age_seconds > 180` | 2m | warn | data older than 3 collection intervals |
| `FritzHighScrapeFailureRate` | `fritz_consecutive_scrape_failures >= 5` | 1m | crit | persistent collection failure |
| `FritzMeshNodeDown` | `fritz_node_up == 0` | 5m | warn | repeater/powerline inactive |
| `FritzWanDownloadSaturated` | `fritz:wan_download_utilization:ratio > 0.9` | 5m | warn | sustained ≥90 % of downstream capacity |
| `FritzWanUploadSaturated` | `fritz:wan_upload_utilization:ratio > 0.9` | 5m | warn | sustained ≥90 % of upstream capacity |
| `FritzExcessiveClientReconnects` | `fritz:device_connection_changes:1h > 10` | 10m | warn | ~5 disconnect cycles/h (edges counted x2) |
| `FritzExcessiveNodeReconnects` | `fritz:node_connection_changes:24h > 8` | 10m | warn | backhaul or power instability |
| `FritzProbeTargetDown` | `probe_success{job=~"probe_.+"} == 0` | 2m | warn | ICMP/DNS target unreachable |
| `FritzHighGatewayLatency` / `FritzCriticalGatewayLatency` | `fritz:probe_rtt_seconds:p95_10m{probe_kind="infra"} > 0.010 / 0.025` | 5m | warn / crit | LAN/AP p95 RTT |
| `FritzHighWanLatency` / `FritzCriticalWanLatency` | `min(...{probe_kind="internet"}) > 0.050 / 0.100` | 5m | warn / crit | p95 RTT to *every* anchor (avoids single-anchor noise) |
| `FritzHighPacketLoss` / `FritzCriticalPacketLoss` | `fritz:probe_loss_ratio:5m{job=~"probe_icmp_.+"} > 0.01 / 0.03` | 5m | warn / crit | failed-probe fraction |
| `FritzDnsSlow` | `fritz:dns_lookup_seconds:p95_10m > 0.2` | 10m | warn | resolver latency |
| `FritzDnsFailing` | `fritz:dns_success_ratio:5m < 0.8` | 5m | crit | resolution failing |
| `FritzCapabilityMissing` | `fritz_capability_available == 0` | 15m | info | account permission nudge — see [fritz-permissions.md](fritz-permissions.md) |
| `FritzHighJitter` | `fritz:probe_jitter_seconds:10m > 0.010` | 10m | warn | unstable path (RTT stddev) |

Roaming / per-AP-load alerts still require the collector change for per-client
access-point attribution; a structured event pipeline (Loki) is not yet built.

## Editing / regenerating

`fritz_noc` and `fritz_client` are generated by a script kept out of the repo
(scratchpad). Hand-edits to the JSON are fine — `provisioning` has
`allowUiUpdates: true` and `updateIntervalSeconds: 10`, so saved changes on disk
reload automatically. Keep `uid`, `schemaVersion` and datasource UIDs stable.
