# Event Pipeline

## Model

The FRITZ!Box **device log** (TR-064 `DeviceInfo:GetDeviceLog` /
`X_AVM-DE_GetDeviceLogPath`) is **not reachable** with the least-privilege
monitoring account this stack uses — every variant returns `401 Unauthorized` /
`Invalid Action` on the target firmware. Reading it would require a FRITZ!Box
user with full settings permission, which defeats the point of a scoped
monitoring account.

So events are **derived**, not scraped: [`src/fritz_monitoring/events.py`](../src/fritz_monitoring/events.py)
diffs each collector snapshot against the previous one and emits structured
events for transitions that can be reconstructed **reliably** from two snapshots.

```
collector.collect_once()
        │  MonitoringSnapshot (prev, curr)
        ▼
events.EventDeriver.process()
        │  derive_events()  — pure function, fully unit-tested
        ▼
loguru INFO/WARNING line:  "fritz_event { …compact JSON… }"  → container stdout
        ▼
Grafana Alloy  loki.source.docker  →  Loki           (see "Known issue" below)
        ▼
Grafana:  fritz_events dashboard  +  fritz_noc "Network events" annotation
```

## Emitted event types (reliably derivable)

| `event_type` | `subsystem` | `severity` | Trigger |
| --- | --- | --- | --- |
| `client_connected` / `client_disconnected` | `client` | info | per-MAC `fritz_device_up` edge, incl. device leaving/joining the host list |
| `node_connected` / `node_disconnected` | `mesh` | info / warning | per-node active edge, incl. node vanishing from the mesh list |
| `mesh_parent_changed` | `mesh` | warning | a node's `parent_node` changed between snapshots |
| `wan_disconnected` / `wan_connected` | `wan` | critical / info | `WanStats.is_connected` edge |
| `wan_ip_changed` | `wan` | info | external IP changed (both values present) |
| `router_restart` | `system` | warning | device uptime decreased by >30 s |

JSON body: `timestamp` (from the snapshot, UTC ISO), `event_type`, `subsystem`,
`severity`, `message`, plus `device`/`mac`/`ip` or `node`/`mac`/`parent` /
`old_ip`/`new_ip` as applicable. High-cardinality fields (MAC, name, IP) stay in
the body — never promoted to Loki stream labels.

### Not derivable today (deliberately absent)

| Wanted | Blocker |
| --- | --- |
| `client_roamed` | needs per-client → access-point attribution (collector fix, still open) |
| `wifi_channel_changed`, `authentication_failure` | only in the device log (401) |

First pass after start emits nothing (no baseline to diff).

## Dashboard

**Network Events & Forensics** (`fritz_events`) — event count/rate by type, a
filtered log viewer (`$event_type`, `$subsystem` variables), most-active-devices
table, infrastructure/WAN event stream. The NOC dashboard gets a "Network
events" Loki annotation for `wan_*`, `node_*`, `mesh_parent_changed`,
`router_restart`.

LogQL used (strips the loguru prefix so `| json` gets a clean object):

```logql
{container=~".+fritz-exporter.+"} |= "fritz_event "
  | pattern "<_>fritz_event <ev>" | line_format "{{.ev}}" | json
  | event_type=~"$event_type" | subsystem=~"$subsystem"
```

## Loki ingestion pipeline — fixed

The container-log path had **never delivered to Loki** (zero streams;
`fritz_logs` was also empty). Root cause: `discovery.docker` runs unscoped, so it
enumerated every container on the host (unrelated stacks included) and emitted
one target *per exposed port* (`__address__ = <ip>:80`, …). `loki.source.docker`
could not tail that target set — `loki.write` received nothing and exported no
metrics.

Fix in [`config/alloy/config.alloy`](../config/alloy/config.alloy):

* `discovery.relabel "containers"` — `keep` only
  `com.docker.compose.project =~ "fritz-monitoring-.*"`, collapsing to one
  target per container, and shape `job` / `container` / `service` stream labels
  at discovery time.
* `loki.source.docker` consumes `discovery.relabel.containers.output`; the
  interim `loki.relabel "containers"` block was removed.
* `loki.write` runs with `wal { enabled = false }` (synchronous sends surface
  errors immediately) + explicit `tenant_id`, `batch_wait`, and a `stack`
  external label.
* `compose.*.yml`: Alloy HTTP bound to `0.0.0.0:12345` and scraped by Prometheus
  (`job="alloy"`) so `loki_write_sent_entries_total` / `_dropped_*` are visible.

Verified: `loki_write_sent_entries_total > 0`, `dropped = 0`; Loki labels
`container,job,service,service_name,stack`; the `fritz_event` LogQL above returns
parsed events end-to-end through Grafana. `fritz_logs` now has data too.
