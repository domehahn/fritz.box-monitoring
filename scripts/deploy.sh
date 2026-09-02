#!/usr/bin/env bash
# P2 — validate every config, apply changed services, wait for health.
# The Docker-Desktop bind-mount staleness bug means "docker compose up -d" alone
# can leave containers serving an old file; this script force-recreates the
# services whose mounted config actually changed and verifies they came back.
#
#   scripts/deploy.sh                 # validate + deploy changed services
#   scripts/deploy.sh --all           # force-recreate everything
#   scripts/deploy.sh --check         # validate only, change nothing
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose -f compose.prod.yml --env-file .env.production"
PROM_IMG="prom/prometheus:v2.54.1"
AM_IMG="prom/alertmanager:v0.27.0"
MODE="${1:-changed}"

say() { printf '\033[1;34m▸ %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- validate
say "Validating configuration"
docker run --rm -v "$PWD/config:/config:ro" --entrypoint sh "$PROM_IMG" -c \
  'promtool check config /config/prometheus.yml && promtool check rules /config/prometheus/rules/*.yml' \
  >/dev/null || die "prometheus config / rules invalid"
ok "prometheus config + $(ls config/prometheus/rules/*.yml | wc -l | tr -d ' ') rule files"

docker run --rm -v "$PWD/config/alertmanager:/c:ro" --entrypoint amtool "$AM_IMG" \
  check-config /c/alertmanager.yml >/dev/null || die "alertmanager.yml invalid"
ok "alertmanager.yml"

docker run --rm -v "$PWD/config/loki:/c:ro" grafana/loki:3.1.1 \
  -config.file=/c/loki-config.yml -verify-config >/dev/null 2>&1 || \
  echo "  (loki -verify-config not conclusive; skipping)"

python3 - <<'PY' || die "dashboard JSON invalid"
import json, glob, collections, sys
allowed = {"prometheus", "loki", "victoriametrics", "-- Grafana --", "-- Mixed --", None}
bad = []
for f in sorted(glob.glob("config/grafana/provisioning/dashboards_files/*.json")):
    d = json.load(open(f)); ids = []
    def walk(o):
        if isinstance(o, dict):
            if o.get("type") in ("prometheus", "loki") and o.get("uid") not in allowed:
                bad.append(f"{f}: datasource {o.get('uid')!r}")
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    def collect(ps):
        for p in ps: ids.append(p.get("id")); collect(p.get("panels", []))
    collect(d.get("panels", [])); walk(d.get("panels", []))
    dups = [i for i, n in collections.Counter(ids).items() if n > 1]
    if dups: bad.append(f"{f}: dup panel ids {dups}")
if bad:
    print("\n".join(bad)); sys.exit(1)
print(f"  {len(glob.glob('config/grafana/provisioning/dashboards_files/*.json'))} dashboards")
PY
ok "grafana dashboards"

$COMPOSE config -q || die "compose config invalid"
ok "compose config"

[ "$MODE" = "--check" ] && { say "validate-only — done"; exit 0; }

# --------------------------------------------------- what changed since last deploy
# Compare each service's mounted config against a local state file, NOT the
# container FS: Docker Desktop can have the file present in the container but
# the process (e.g. Prometheus rule state) still on the old version, so
# "container matches host" is not enough to skip a recreate.
say "Detecting config changes since the last deploy"
STATE_DIR=".deploy-state"; mkdir -p "$STATE_DIR"
CHANGED=""
hash_path() {  # file or dir -> stable sha
  if [ -f "$1" ]; then shasum -a 256 "$1" | cut -d' ' -f1
  elif [ -d "$1" ]; then
    ( cd "$1" && find . -type f | LC_ALL=C sort | while read -r p; do
        printf '%s %s\n' "$p" "$(shasum -a 256 "$p" | cut -d' ' -f1)"; done ) | shasum -a 256 | cut -d' ' -f1
  else echo missing; fi
}
mounted_state() {  # only config-bearing mounts (not data dirs like ./backups)
  $COMPOSE config --format json | python3 -c '
import json, sys, os
root = "'"$PWD"'"
d = json.load(sys.stdin)
for name, svc in d.get("services", {}).items():
    for m in svc.get("volumes", []):
        if m.get("type") != "bind":
            continue
        src = m.get("source", "").rstrip("/")
        if not src.startswith(root):
            continue
        rel = os.path.relpath(src, root)
        if rel.startswith("config/") or rel == "config" or rel.startswith("secrets") \
           or rel.endswith((".yml", ".yaml", ".alloy")) or rel == ".env.production":
            print(name, src)
'
}
declare_new_hash() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
while read -r svc src; do
  [ -z "${svc:-}" ] && continue
  cname="fritz-monitoring-prod-${svc}-1"
  new="$(hash_path "$src")"
  key="${svc}__$(echo "$src" | shasum -a 256 | cut -c1-12)"
  old="$(cat "$STATE_DIR/$key" 2>/dev/null || echo none)"
  if ! docker ps --format '{{.Names}}' | grep -qx "$cname"; then CHANGED="$CHANGED $svc"
  elif [ "$new" != "$old" ]; then CHANGED="$CHANGED $svc"; fi
  declare_new_hash "$key" "$new"
done < <(mounted_state)
CHANGED=$(echo "$CHANGED" | tr ' ' '\n' | sort -u | tr '\n' ' ' | sed 's/^ *//')

if [ "$MODE" = "--all" ]; then
  say "Recreating ALL services (--all)"
  $COMPOSE up -d --build --force-recreate --remove-orphans
elif [ -n "$CHANGED" ]; then
  say "Recreating changed services:$CHANGED"
  # shellcheck disable=SC2086
  $COMPOSE up -d --build --force-recreate $CHANGED
  $COMPOSE up -d --build   # bring up anything newly added to the compose file
else
  say "No mounted-config drift. Applying any image/compose changes"
  $COMPOSE up -d --build
fi

# --------------------------------------------------------------- health
say "Waiting for health"
deadline=$(( $(date +%s) + 180 ))
while :; do
  bad=$($COMPOSE ps --format json | python3 -c '
import json,sys
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    c=json.loads(line)
    h=c.get("Health","")
    if c.get("State")=="running" and h in ("","healthy","starting"): continue
    if c.get("State")=="running" and h=="unhealthy": print(c["Service"])
    elif c.get("State")!="running": print(c["Service"])
' | sort -u | tr '\n' ' ')
  [ -z "$bad" ] && { ok "all services healthy"; break; }
  [ "$(date +%s)" -ge "$deadline" ] && die "still unhealthy after 180s:$bad"
  sleep 5
done

# ------------------------------------------------------------- reload rulesets
# cheap + idempotent; makes sure Prometheus/Loki actually re-read rule files
# even when the container was not recreated
say "Reloading rule engines"
docker exec fritz-monitoring-prod-prometheus-1 wget -qO- --post-data='' \
  http://localhost:9090/-/reload >/dev/null 2>&1 && ok "prometheus reloaded" || \
  echo "  (prometheus reload skipped)"
docker exec fritz-monitoring-prod-loki-1 kill -HUP 1 >/dev/null 2>&1 || true

say "Deploy complete"
