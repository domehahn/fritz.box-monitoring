# Smart-home exporters (opt-in)

Four small Prometheus exporters that widen the stack from "the network" to "the
things on the network": **Hue**, **Bosch Smart Home**, **Blink**, and
**FRITZ!DECT**. They share the running Prometheus / Loki / Grafana backend and
never touch the FRITZ!Box exporter.

* Package: `src/home_iot/` — one sub-package per vendor, same shape as
  `fritz_monitoring.iperf` (`*Config.from_env()` → `*Exporter` → `render()`).
* Image: `docker/Dockerfile.home_iot` (one image, four entrypoints).
* Compose: services `hue-exporter` / `bosch-exporter` / `blink-exporter` /
  `fritzdect-exporter`, each behind its own profile.
* Dashboard: **Smart Home Fleet** (`smarthome.json`).
* Alerts: `config/prometheus/rules/smarthome_alerts.yml`.

Every exporter **starts and stays healthy with no configuration**, serving
`<vendor>_configured 0` and `<vendor>_up 0`. So it is safe to enable the whole
`smarthome` profile before you have paired a single hub, and the alert rules
stay silent until `*_configured` flips to 1.

| Exporter | Port | Transport | Extra deps | Reliability |
|----------|------|-----------|-----------|-------------|
| `home_iot.hue` | 9120 | local HTTPS (CLIP v2) | none | high |
| `home_iot.bosch` | 9121 | local REST + client cert | `boschshcpy` | high |
| `home_iot.blink` | 9122 | Amazon cloud | `blinkpy` | low (cloud, rate-limited) |
| `home_iot.fritzdect` | 9123 | TR-064 `X_AVM-DE_Homeauto` | none | high |

```bash
# all four
docker compose -f compose.prod.yml --profile smarthome up -d --build
# or just one
docker compose -f compose.prod.yml --profile hue up -d --build
```

`docker compose --profile smarthome ... down` (or dropping the profile flag on
the next `up`) removes them; nothing else in the stack changes.

---

## "Is it enabled, or just broken?"

Each exporter exposes both flags so a disabled profile never looks like an
outage:

| `*_configured` | `*_up` | Meaning |
|:---:|:---:|---|
| 0 | 0 | Not set up — expected, nothing to do. |
| 1 | 0 | Configured but the hub is unreachable / auth failed → look at container logs. |
| 1 | 1 | Working. |

The scrape target itself is **DOWN** in Prometheus whenever the compose profile
is off — also expected, same as the `iperf_probe` job.

---

## 1 · Philips Hue (`:9120`)

Local API, no cloud, no account.

1. Find the bridge IP (FRITZ!Box device list, or `https://discovery.meethue.com`).
2. Create an application key — press the round link button on the bridge, then
   within 30 s:

   ```bash
   curl -sk -X POST https://<bridge-ip>/api \
     -d '{"devicetype":"fritz-monitoring#exporter","generateclientkey":true}'
   # -> [{"success":{"username":"<APP_KEY>", ...}}]
   ```

3. Store the key and point the exporter at it:

   ```bash
   echo -n '<APP_KEY>' > secrets/hue_app_key.txt      # ./secrets is git-ignored
   ```
   ```ini
   HUE_BRIDGE_HOST=192.168.178.30
   HUE_APP_KEY=/secrets/hue_app_key.txt               # literal key also accepted
   ```

The bridge serves a self-signed cert, so TLS verification is **off** by default.
To pin it, set `HUE_VERIFY_TLS=true` and `HUE_CA_FILE=/secrets/huebridge_cacert.pem`
(the Hue root CA is published by Signify).

Key metrics: `hue_zigbee_connectivity_status` (0 = a bulb/accessory fell off the
Zigbee mesh — the early-warning signal), `hue_device_battery_percent`,
`hue_sensor_temperature_celsius`, `hue_sensor_light_level_lux`,
`hue_sensor_motion`, `hue_light_on` / `hue_light_brightness_percent`.

---

## 2 · Bosch Smart Home Controller (`:9121`)

Local REST API secured with a client certificate you pair once.

1. Generate a key pair:

   ```bash
   openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
     -keyout secrets/bosch-shc-key.pem -out secrets/bosch-shc-cert.pem \
     -subj "/CN=fritz-monitoring"
   ```

2. Register it with the SHC, pressing the controller button when prompted:

   ```bash
   poetry run python -m boschshcpy.register_client \
     -shc <shc-ip> -cert secrets/bosch-shc-cert.pem -key secrets/bosch-shc-key.pem
   ```

3. Configure:

   ```ini
   BOSCH_SHC_HOST=192.168.178.31
   BOSCH_SHC_CERT_FILE=/secrets/bosch-shc-cert.pem
   BOSCH_SHC_KEY_FILE=/secrets/bosch-shc-key.pem
   ```

`./secrets` mounts read-only at `/secrets` in the container.

Key metrics: `bosch_device_available`, `bosch_device_battery_ok` /
`bosch_shc_battery_low_count`, `bosch_device_fault` / `bosch_shc_fault_count`
(smoke/water alarms surface here), `bosch_device_temperature_celsius`,
`bosch_device_humidity_percent`, `bosch_device_valve_percent`,
`bosch_shc_update_available`.

---

## 3 · Blink (`:9122`)

No local API — this talks to Amazon's cloud through the unofficial `blinkpy`.
It is **cloud rate-limited**, so the interval floors at 300 s and defaults to
600 s. Treat the numbers as best-effort.

1. First run — supply the account and the one-time 2FA code Amazon sends:

   ```ini
   BLINK_USERNAME=you@example.com
   BLINK_PASSWORD=...
   BLINK_2FA_KEY=123456
   ```

2. On success `blinkpy` writes a reusable token to
   `/data/blink.json` (the `home_iot_data` volume). After that, remove
   `BLINK_2FA_KEY`; `BLINK_USERNAME` / `BLINK_PASSWORD` stay as a fallback for
   token refresh.

Key metrics: `blink_sync_module_online` (0 = every camera behind it is blind),
`blink_camera_battery_ok`, `blink_camera_battery_millivolts`,
`blink_camera_temperature_celsius`, `blink_camera_wifi_strength`,
`blink_camera_motion_enabled` / `blink_camera_motion_detected`.

> The credentials pass through Amazon. If you would rather not run this, the
> cameras are still visible as Wi-Fi clients on the **Client Diagnostics**
> dashboard (reachability only).

---

## 4 · FRITZ!DECT (`:9123`)

Reuses the FRITZ!Box the main exporter already talks to — no new credentials.
Enable the `fritzdect` (or `smarthome`) profile and it works. Optional:

```ini
FRITZDECT_INTERVAL_SECONDS=60
```

Covered hardware: FRITZ!DECT 200/210 sockets (`fritzdect_power_watts`,
`fritzdect_energy_watt_hours_total`, `fritzdect_temperature_celsius`,
`fritzdect_switch_on`), FRITZ!DECT 301/302 radiator controls
(`fritzdect_hkr_set_celsius`, `fritzdect_hkr_comfort_celsius`,
`fritzdect_hkr_valve_open`), and `fritzdect_device_present` for every DECT
device.

---

## Not exposed (and why)

* **Per-band Wi-Fi / airtime load of the Hue bridge or Blink modules** —
  none of these hubs report it.
* **Zigbee LQI per Hue device** — only in the deprecated Hue v1 API; not worth
  the second code path yet. `hue_zigbee_connectivity_status` covers the
  "is it on the mesh" question.
* **Bosch scenarios / automations state** — out of scope for a health exporter.
* **Blink video / thumbnails** — not metrics.

## Cardinality

One series per device per metric. A typical home (30 Hue, 20 Bosch, 6 Blink,
5 DECT) is well under 2k series total across all four exporters — negligible for
this Prometheus.
