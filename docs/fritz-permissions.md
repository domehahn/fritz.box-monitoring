# FRITZ!Box account permissions

Several diagnostic features depend on the FRITZ!Box **user account** the exporter
logs in with. A deliberately minimal ("voip/dslf" style) account can read WAN,
DSL, host list and aggregate counters, but the box returns **`401 Invalid
Action`** for the actions that back mesh topology, per-client Wi-Fi and the event
log.

The exporter probes these once at startup and exposes the result:

```promql
fritz_capability_available{feature="mesh_topology"}     # 0 on a minimal account
fritz_capability_available{feature="wlan_associations"}
fritz_capability_available{feature="device_log"}
```

A `0` also produces one WARNING line in the exporter log naming the exact
setting to change, and fires the `FritzCapabilityMissing` alert.

## What each capability unlocks

| `feature` | TR-064 action | Unlocks |
| --- | --- | --- |
| `mesh_topology` | `Hosts1:X_AVM-DE_GetMeshListPath` | Mesh hierarchy & the `fritz_mesh` topology graph edges (`fritz_node_parent`); per-repeater backhaul link rates (`fritz_node_link_*_kbps`); per-client → access-point attribution (`fritz_device_up{node=…}`), which in turn enables `fritz_repeater_connected_devices`, per-AP load and **roaming** events |
| `wlan_associations` | `WLANConfiguration{1,2,3}:GetGenericAssociatedDeviceInfo` | Per-client Wi-Fi **signal strength** and negotiated **PHY rate** (`fritz_device_wlan_signal_strength`, `fritz_device_wlan_speed_mbps`), across all bands |
| `device_log` | `DeviceInfo1:GetDeviceLog` | The FRITZ!Box event log as first-class events (Wi-Fi channel changes, authentication failures, firmware/reboot events) alongside the snapshot-derived events |

Everything else in the stack — the NOC dashboard, WAN utilisation, flap
statistics, active probing (Blackbox), snapshot-derived connect/disconnect/WAN
events, the Repeater Health Matrix's availability + flap columns — works on a
minimal account.

## How to grant it

On the FRITZ!Box web UI:

1. **System → FRITZ!Box-Benutzer** → edit the monitoring user (or create a
   dedicated one).
2. Enable **"FRITZ!Box Einstellungen"** (FRITZ!Box Settings) for that user.
   Leave the other rich permissions (VPN, phone, smart home) off — only Settings
   is required.
3. **Heimnetz → Netzwerk → Netzwerkeinstellungen**: ensure
   **"Zugriff für Anwendungen zulassen"** (allow access for applications) and
   **"Statusinformationen … über UPnP übertragen"** are enabled.
4. If the exporter authenticates over the LAN with username+password (not the
   `dslf-config` auto-user), make sure the user is allowed **"von außen"** is
   *not* needed — LAN access is enough.
5. Restart the exporter (`docker compose -f compose.prod.yml up -d
   --force-recreate fritz-exporter`). The capability probe re-runs; the metrics
   flip to `1` and the previously-empty panels populate on the next collection
   cycle. No dashboard or rule changes needed.

## Security note

Granting "FRITZ!Box Settings" lets the account **read** configuration and the
event log. It does not by itself allow changing settings via TR-064 unless the
specific write actions are also used (the exporter never calls any). Use a
dedicated user, a strong password stored via `secrets/fritz_password.txt`, and
keep TR-064 reachable only from the trusted LAN.
