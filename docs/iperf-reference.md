# iperf3 LAN reference probe (opt-in)

Purpose: tell **"slow LAN / Wi-Fi"** apart from **"slow WAN / ISP"** by
periodically measuring achievable throughput to a wired host on your own
network, and comparing it with the WAN metrics on the NOC.

**Disabled by default.** It is a compose profile (`iperf`) and does nothing
unless `IPERF_TARGET` is set.

## Safety design

* Interval is **floored at 600 s** (`IPERF_INTERVAL_SECONDS`, default 21600 =
  6 h). A shorter value is silently raised to 600 s.
* Test duration is **capped at 30 s** (`IPERF_DURATION_SECONDS`, default 5 s).
* Optional hard cap `IPERF_BITRATE` (e.g. `200M`) passed straight to `iperf3 -b`.

At default settings a run is 5 s every 6 h — a ~0.02 % duty cycle. Even at line
rate it cannot "continuously consume bandwidth".

## Enable it

1. On a **wired** LAN host (NAS, mini-PC — not Wi-Fi), run a server:

   ```bash
   iperf3 -s            # listens on tcp/5201
   ```

2. Set the target (and any overrides) in `.env.production`:

   ```ini
   IPERF_TARGET=192.168.178.20
   # IPERF_INTERVAL_SECONDS=21600
   # IPERF_DURATION_SECONDS=5
   # IPERF_BITRATE=
   # IPERF_REVERSE=false      # true also measures download (server -> client)
   ```

3. Start the profile:

   ```bash
   docker compose -f compose.prod.yml --profile iperf --env-file .env.production up -d
   ```

Prometheus scrapes `iperf-probe:9119` (job `iperf_probe`). Until enabled the
target shows **down** — that is expected.

## Metrics

| Metric | Meaning |
| --- | --- |
| `iperf_enabled` | 1 if `IPERF_TARGET` is configured |
| `iperf_last_run_success` | 1 if the last test completed |
| `iperf_last_run_timestamp_seconds` | Unix time of the last test |
| `iperf_sent_bits_per_second` | Upload throughput (client → server) |
| `iperf_received_bits_per_second` | Download throughput (with `IPERF_REVERSE=true`) |
| `iperf_retransmits` | TCP retransmits in the last test |

Shown on **Network Path Probes** → "iperf3 LAN reference throughput". Compare
against WAN throughput on the NOC: LAN near line rate + WAN slow ⇒ ISP/line;
LAN also slow ⇒ local switching/cabling/host.
