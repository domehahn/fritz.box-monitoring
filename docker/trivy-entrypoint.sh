#!/bin/sh
# Scan every image used by a running stack container for HIGH/CRITICAL CVEs and
# write a Prometheus textfile that node-exporter picks up.
set -eu

PROXY="${DOCKER_HOST:-http://docker-socket-proxy:2375}"
PROXY="${PROXY#tcp://}"; PROXY="${PROXY#http://}"
INTERVAL_HOURS="${TRIVY_INTERVAL_HOURS:-168}"   # weekly
TEXTFILE="${TRIVY_TEXTFILE:-/textfile/trivy.prom}"
export TRIVY_CACHE_DIR=/cache

PROJECT="${COMPOSE_PROJECT:-fritz-monitoring-prod}"

images() {  # only images used by THIS compose project's running containers
  flt=$(jq -rn --arg p "$PROJECT" \
        '{"label":["com.docker.compose.project=" + $p]} | @uri')
  wget -qO- "http://${PROXY}/containers/json?filters=${flt}" \
    | jq -r '.[].Image' | sort -u | grep -v '^sha256:'
}

run_once() {
  start=$(date +%s); ok=1
  tmp="${TEXTFILE}.$$"
  {
    echo "# HELP trivy_image_vulnerabilities HIGH/CRITICAL CVEs per image."
    echo "# TYPE trivy_image_vulnerabilities gauge"
  } > "$tmp"
  for img in $(images); do
    echo "[trivy] $img"
    if ! json=$(trivy image --quiet --scanners vuln --severity HIGH,CRITICAL \
                  --format json --timeout 10m "$img" 2>/dev/null); then
      ok=0; continue
    fi
    for sev in HIGH CRITICAL; do
      c=$(printf '%s' "$json" | jq --arg s "$sev" \
            '[.Results[]?.Vulnerabilities[]? | select(.Severity==$s)] | length')
      esc=$(printf '%s' "$img" | sed 's/\\/\\\\/g; s/"/\\"/g')
      printf 'trivy_image_vulnerabilities{image="%s",severity="%s"} %s\n' \
        "$esc" "$sev" "${c:-0}" >> "$tmp"
    done
  done
  now=$(date +%s)
  {
    echo "# HELP trivy_last_scan_timestamp_seconds Unix time of the last scan."
    echo "# TYPE trivy_last_scan_timestamp_seconds gauge"
    echo "trivy_last_scan_timestamp_seconds ${now}"
    echo "# HELP trivy_last_scan_success 1 if every image scanned cleanly."
    echo "# TYPE trivy_last_scan_success gauge"
    echo "trivy_last_scan_success ${ok}"
    echo "# HELP trivy_last_scan_duration_seconds"
    echo "# TYPE trivy_last_scan_duration_seconds gauge"
    echo "trivy_last_scan_duration_seconds $(( now - start ))"
  } >> "$tmp"
  mv "$tmp" "$TEXTFILE"
  echo "[trivy] done in $(( now - start ))s (ok=$ok)"
}

[ "${1:-loop}" = "once" ] && { run_once; exit 0; }
echo "[trivy] loop every ${INTERVAL_HOURS}h"
while true; do run_once || echo "[trivy] scan errored"; sleep "$(( INTERVAL_HOURS * 3600 ))"; done
