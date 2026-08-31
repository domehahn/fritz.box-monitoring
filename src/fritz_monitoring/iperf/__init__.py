"""Optional, opt-in iperf3 LAN reference probe.

Runs a short iperf3 client test on a long interval against an operator-run
``iperf3 -s`` on a wired LAN host, and exposes the result as Prometheus metrics.
Purpose: tell "slow LAN / Wi-Fi" apart from "slow WAN / ISP". Disabled unless
``IPERF_TARGET`` is set; interval is floored and duration capped so it can never
continuously consume bandwidth.
"""
