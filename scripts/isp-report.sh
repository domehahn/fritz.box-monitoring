#!/usr/bin/env bash
# Export a month of speed measurements as CSV — the evidence to attach to an
# ISP complaint. Reads from VictoriaMetrics (months of history).
#
#   scripts/isp-report.sh 2026-08            > august.csv
#   VM_URL=http://localhost:8428 scripts/isp-report.sh 2026-08
set -euo pipefail

MONTH="${1:-$(date -u +%Y-%m)}"
VM_URL="${VM_URL:-}"
VM_CONTAINER="${VM_CONTAINER:-fritz-monitoring-prod-victoriametrics-1}"
STEP="${ISP_REPORT_STEP:-1h}"

# month bounds (UTC)
start="$(date -u -d "${MONTH}-01T00:00:00Z" +%s 2>/dev/null \
        || date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "${MONTH}-01T00:00:00Z" +%s)"
end="$(( start + 32*86400 ))"
end="$(date -u -d "@${end}" +%Y-%m-01T00:00:00Z 2>/dev/null \
      || date -u -r "${end}" +%Y-%m-01T00:00:00Z)"
end="$(date -u -d "${end}" +%s 2>/dev/null \
      || date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "${end}" +%s)"

q() {
  local expr="$1"
  local path="/api/v1/query_range?query=$(printf '%s' "$expr" | jq -sRr @uri)&start=${start}&end=${end}&step=${STEP}"
  if [ -n "$VM_URL" ]; then
    curl -sf "${VM_URL}${path}"
  else
    docker exec "$VM_CONTAINER" wget -qO- "http://127.0.0.1:8428${path}"
  fi
}

join_series() {
  # merge down/up/attainment range results into one CSV keyed by timestamp
  jq -rn '
    [ inputs ]
    | (.[0].data.result[0].values // []) as $d
    | (.[1].data.result[0].values // []) as $u
    | (.[2].data.result[0].values // []) as $a
    | ($u | map({(.[0]|tostring): .[1]}) | add // {}) as $um
    | ($a | map({(.[0]|tostring): .[1]}) | add // {}) as $am
    | "timestamp_utc,download_mbps,upload_mbps,pct_of_reference",
      ( $d[]
        | (.[0]|tostring) as $t
        | [ ($t|tonumber|todateiso8601),
            (.[1]|tonumber|.*100|round/100),
            (($um[$t] // "") | if .=="" then "" else (tonumber*100|round/100) end),
            (($am[$t] // "") | if .=="" then "" else (tonumber*100|round) end)
          ] | @csv )
  '
}

{ q 'isp:measured:down_mbps'; q 'isp:measured:up_mbps'; q 'isp:attainment:down_ratio'; } \
  | join_series

echo "# month=${MONTH} step=${STEP}  reference: $(q 'isp:reference:down_mbps' \
      | jq -r '.data.result[0].values[-1][1] // "n/a" | if .=="n/a" then . else (tonumber|round|tostring)+" Mbit/s" end')" >&2
