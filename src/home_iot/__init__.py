"""Standalone Prometheus exporters for the smart-home fleet.

Each sub-package (:mod:`home_iot.hue`, :mod:`home_iot.bosch`,
:mod:`home_iot.blink`, :mod:`home_iot.fritzdect`) is a small, self-contained
exporter that serves ``/metrics`` + ``/healthz`` on its own port and polls one
vendor hub on a fixed interval. They share the running Prometheus / Loki /
Grafana backend but never import from — or interfere with — the FRITZ!Box
exporter.

Nothing here talks to a device at import time; every collector degrades to
``*_up 0`` when it is unconfigured or the hub is unreachable, so a container
with no credentials still starts and stays healthy.
"""
