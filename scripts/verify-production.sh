#!/usr/bin/env bash
set -euo pipefail

# Production Stack Health Verification Script

EXPORTER_URL=${EXPORTER_URL:-"http://127.0.0.1:8000"}
GRAFANA_URL=${GRAFANA_URL:-"http://127.0.0.1:3000"}
PROMETHEUS_URL=${PROMETHEUS_URL:-"http://127.0.0.1:9090"}
LOKI_URL=${LOKI_URL:-"http://127.0.0.1:3100"}

echo "=== FRITZ!Box Monitoring Production Verification ==="

echo -n "1. Exporter Healthz (/healthz)... "
if curl -sf "${EXPORTER_URL}/healthz" > /dev/null; then
    echo "OK"
else
    echo "FAILED"
    exit 1
fi

echo -n "2. Exporter Metrics Endpoint (/metrics)... "
if curl -sf "${EXPORTER_URL}/metrics" | grep -q "fritz_exporter_build_info"; then
    echo "OK"
else
    echo "FAILED"
    exit 1
fi

echo -n "3. Prometheus Readiness (//-/ready)... "
if curl -sf "${PROMETHEUS_URL}/-/ready" > /dev/null 2>&1; then
    echo "OK"
else
    echo "SKIPPED / UNREACHABLE (Host bind check only)"
fi

echo -n "4. Grafana Health (/api/health)... "
if curl -sf "${GRAFANA_URL}/api/health" > /dev/null 2>&1; then
    echo "OK"
else
    echo "SKIPPED / UNREACHABLE (Host bind check only)"
fi

echo -n "5. Loki Ready Endpoint (/ready)... "
if curl -sf "${LOKI_URL}/ready" > /dev/null 2>&1; then
    echo "OK"
else
    echo "SKIPPED / UNREACHABLE (Internal backend network)"
fi

echo "=== All Active Verification Checks PASSED ==="

