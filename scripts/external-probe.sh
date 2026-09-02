#!/usr/bin/env bash
# Probe the home connection from *outside* — run from GitHub Actions (or any
# off-site host). Internal blackbox probes can't see an ISP outage, a dead
# DynDNS updater, or a public-IP change; this can.
#
# Checks:
#   1. current public IPv4 (api.ipify.org)
#   2. every URL in PROBE_TARGETS / the targets file  -> HTTP status + TLS days-left
#   3. PROBE_DDNS_HOST resolves, and its A record matches the public IP
#
# On any failure: POST a summary to ntfy ($NTFY_URL/$NTFY_TOPIC) and exit 1.
# Writes a table to $GITHUB_STEP_SUMMARY when present.
set -uo pipefail

TARGETS_FILE="${PROBE_TARGETS_FILE:-config/external-probe/targets.txt}"
TLS_WARN_DAYS="${PROBE_TLS_WARN_DAYS:-21}"
CURL="curl -sS --max-time 20"
fail=0
lines=()

say()  { printf '%s\n' "$*"; lines+=("$*"); }
bad()  { printf '\033[31m%s\033[0m\n' "$*"; lines+=("$*"); fail=1; }

# ---------------------------------------------------------------- public IP
pubip="$($CURL https://api.ipify.org || true)"
if [[ "$pubip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  say "✅ public IP: $pubip"
else
  bad "❌ could not determine public IP (got '${pubip:-}')"
  pubip=""
fi

# ---------------------------------------------------------------- targets
mapfile -t urls < <(
  { [ -n "${PROBE_TARGETS:-}" ] && tr ' ,' '\n' <<<"$PROBE_TARGETS"; \
    [ -f "$TARGETS_FILE" ] && sed 's/#.*//' "$TARGETS_FILE"; } \
  | sed '/^[[:space:]]*$/d' | sort -u
)

for url in "${urls[@]}"; do
  code="$($CURL -o /dev/null -w '%{http_code}' -L "$url")"; code="${code:-000}"
  if [[ "$code" =~ ^(2|3)[0-9][0-9]$ ]]; then
    say "✅ $url -> $code"
  else
    bad "❌ $url -> $code"
  fi

  host="${url#*://}"; host="${host%%/*}"; host="${host%%:*}"
  port="443"; [[ "$url" == http://* ]] && port="80"
  if [ "$port" = "443" ]; then
    end="$(echo | openssl s_client -connect "$host:$port" -servername "$host" 2>/dev/null \
           | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"
    if [ -n "$end" ]; then
      secs=$(( $(date -d "$end" +%s 2>/dev/null || echo 0) - $(date +%s) ))
      days=$(( secs / 86400 ))
      if [ "$days" -lt 0 ]; then
        bad "❌ $host TLS cert EXPIRED"
      elif [ "$days" -lt "$TLS_WARN_DAYS" ]; then
        bad "⚠️  $host TLS cert expires in ${days}d"
      else
        say "✅ $host TLS ok (${days}d left)"
      fi
    fi
  fi
done

# ---------------------------------------------------------------- DynDNS
if [ -n "${PROBE_DDNS_HOST:-}" ]; then
  resolved="$(getent ahostsv4 "$PROBE_DDNS_HOST" 2>/dev/null | awk 'NR==1{print $1}')"
  [ -z "$resolved" ] && resolved="$(nslookup "$PROBE_DDNS_HOST" 2>/dev/null | awk '/^Address: /{print $2; exit}')"
  if [ -z "$resolved" ]; then
    bad "❌ $PROBE_DDNS_HOST does not resolve"
  elif [ -n "$pubip" ] && [ "$resolved" != "$pubip" ]; then
    bad "❌ $PROBE_DDNS_HOST -> $resolved but public IP is $pubip (DynDNS updater stuck?)"
  else
    say "✅ $PROBE_DDNS_HOST -> $resolved (matches public IP)"
  fi
fi

# ---------------------------------------------------------------- report
report="$(printf '%s\n' "${lines[@]}")"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  { echo "### External probe $(date -u +%FT%TZ)"; echo '```'; echo "$report"; echo '```'; } \
    >> "$GITHUB_STEP_SUMMARY"
fi

if [ "$fail" -ne 0 ] && [ -n "${NTFY_TOPIC:-}" ]; then
  ${CURL} \
    -H "Title: External probe FAILED" \
    -H "Priority: 4" -H "Tags: warning,globe_with_meridians" \
    -d "$report" \
    "${NTFY_URL:-https://ntfy.sh}/${NTFY_TOPIC}" >/dev/null || true
fi

printf '\n%s\n' "$report"
exit "$fail"
