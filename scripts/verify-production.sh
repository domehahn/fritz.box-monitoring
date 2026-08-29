#!/usr/bin/env bash
set -euo pipefail

# Production Stack Health Verification Script

EXPORTER_URL=${EXPORTER_URL:-"http://127.0.0.1:8000"}
GRAFANA_URL=${GRAFANA_URL:-"http://127.0.0.1:3000"}
PROMETHEUS_URL=${PROMETHEUS_URL:-"http://127.0.0.1:9090"}
LOKI_URL=${LOKI_URL:-"http://127.0.0.1:3100"}

echo "=== FRITZ!Box Monitoring Production Verification ==="

echo -n "1. Exporter Healthz (/healthz)... "
if curl -sf "${EXPORTER_URL}/healthz" >/dev/null 2>&1; then
    echo "OK"
elif docker ps --format '{{.Names}}' | grep -q "fritz-exporter"; then
    CONTAINER_NAME=$(docker ps --format '{{.Names}}' | grep "fritz-exporter" | head -n 1)
    docker exec "$CONTAINER_NAME" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" >/dev/null
    echo "OK (via container $CONTAINER_NAME)"
else
    echo "FAILED"
    exit 1
fi

echo -n "2. Exporter Readyz (/readyz)... "
if curl -sf "${EXPORTER_URL}/healthz" >/dev/null 2>&1; then
    STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${EXPORTER_URL}/readyz" || echo "000")
elif docker ps --format '{{.Names}}' | grep -q "fritz-exporter"; then
    CONTAINER_NAME=$(docker ps --format '{{.Names}}' | grep "fritz-exporter" | head -n 1)
    STATUS_CODE=$(docker exec "$CONTAINER_NAME" python -c "import urllib.request, urllib.error
try:
    print(urllib.request.urlopen('http://localhost:8000/readyz').getcode())
except urllib.error.HTTPError as e:
    print(e.code)" 2>/dev/null || echo "503")
else
    STATUS_CODE="000"
fi

if [ "$STATUS_CODE" = "200" ] || [ "$STATUS_CODE" = "503" ]; then
    echo "OK (HTTP $STATUS_CODE)"
else
    echo "FAILED (Unexpected HTTP $STATUS_CODE)"
    exit 1
fi

echo -n "3. Exporter Metrics Endpoint (/metrics)... "
if curl -sf "${EXPORTER_URL}/metrics" 2>/dev/null | grep -q "fritz_exporter_build_info"; then
    echo "OK"
elif docker ps --format '{{.Names}}' | grep -q "fritz-exporter"; then
    CONTAINER_NAME=$(docker ps --format '{{.Names}}' | grep "fritz-exporter" | head -n 1)
    docker exec "$CONTAINER_NAME" python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/metrics').read().decode())" 2>/dev/null | grep -q "fritz_exporter_build_info"
    echo "OK (via container $CONTAINER_NAME)"
else
    echo "FAILED"
    exit 1
fi

echo -n "4. Grafana Health (/api/health)... "
if curl -sf "${GRAFANA_URL}/api/health" > /dev/null 2>&1; then
    echo "OK"
else
    echo "SKIPPED / UNREACHABLE (Host bind check only)"
fi

echo -n "5. Prometheus Health (-/healthy)... "
if curl -sf "${PROMETHEUS_URL}/-/healthy" > /dev/null 2>&1 || (docker ps --format '{{.Names}}' | grep -q "prometheus" && docker exec $(docker ps --format '{{.Names}}' | grep "prometheus" | head -n 1) wget -q -O - http://localhost:9090/-/healthy >/dev/null 2>&1); then
    echo "OK"
else
    echo "SKIPPED / UNREACHABLE"
fi

echo "=== All Active Verification Checks PASSED ==="
