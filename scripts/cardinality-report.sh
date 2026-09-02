#!/usr/bin/env bash
# Where the time series live. Point at Prometheus and get the worst offenders:
# total head series, series per job, series per metric name, and the churniest
# labels. Run after adding an exporter or when PrometheusHighCardinality fires.
#
#   scripts/cardinality-report.sh                 # talks to the running container
#   PROM_URL=http://localhost:9090 scripts/cardinality-report.sh
set -euo pipefail

PROM_URL="${PROM_URL:-}"
CONTAINER="${PROM_CONTAINER:-fritz-monitoring-prod-prometheus-1}"
TOPN="${TOPN:-25}"

q() {
  local expr="$1"
  if [ -n "$PROM_URL" ]; then
    curl -sf --get "$PROM_URL/api/v1/query" --data-urlencode "query=$expr"
  else
    docker exec "$CONTAINER" wget -qO- \
      "http://127.0.0.1:9090/api/v1/query?query=$(printf '%s' "$expr" | jq -sRr @uri)"
  fi
}

row() { # pretty-print a vector result: "<value>  <labelset>"
  jq -r '.data.result[]
    | ((.value[1] | tonumber | floor | tostring)
       + "\t"
       + (.metric | to_entries | map(.value) | join(" ")))' \
    | sort -rn | head -n "$TOPN" | awk -F'\t' '{printf "  %10s  %s\n", $1, $2}'
}

scalar() { q "$1" | jq -r 'if (.data.result | length) == 0 then "n/a" else (.data.result[0].value[1] | tonumber | floor) end'; }

echo "── total ─────────────────────────────────────────────"
printf "  head series      : %s\n" "$(scalar 'prometheus_tsdb_head_series')"
printf "  head chunks      : %s\n" "$(scalar 'prometheus_tsdb_head_chunks')"
printf "  ingest samples/s : %s\n" "$(scalar 'sum(rate(prometheus_tsdb_head_samples_appended_total[5m]))')"
printf "  tsdb bytes       : %s\n" "$(scalar 'prometheus_tsdb_storage_blocks_bytes')"
[ "$(scalar 'prometheus_tsdb_head_series')" = "n/a" ] && \
  echo "  (no prometheus_tsdb_* — is the 'prometheus' self-scrape job up yet?)"

echo
echo "── series per job (top $TOPN) ────────────────────────"
q 'sort_desc(count by (job) ({__name__=~".+"}))' | row

echo
echo "── series per metric name (top $TOPN) ────────────────"
q "topk($TOPN, count by (__name__) ({__name__=~\".+\"}))" | row

echo
echo "── biggest label fan-out: distinct values per label ──"
echo "   (scan the top metrics above, then:)"
echo "   q 'count(count by (<label>) (<metric>))'"

echo
echo "── scrape cost per target (samples, top $TOPN) ───────"
q 'sort_desc(scrape_samples_scraped)' | row
