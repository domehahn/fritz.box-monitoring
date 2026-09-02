#!/bin/sh
# restic backup loop for the fritz-monitoring stack.
# Backs up every data volume + the config/secrets/.env, prunes to a retention
# policy, and writes a Prometheus textfile that node-exporter picks up.
set -eu

INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"
TEXTFILE="${BACKUP_TEXTFILE:-/textfile/backup.prom}"
PATHS="/data /project"
KEEP="${RESTIC_KEEP:---keep-daily 7 --keep-weekly 4 --keep-monthly 6}"

write_metrics() {
  # $1 success(0/1)  $2 duration_s
  ok="$1"; dur="$2"; now="$(date +%s)"
  snaps="$(restic snapshots --json 2>/dev/null | grep -o '"id"' | wc -l | tr -d ' ' || echo 0)"
  size="$(restic stats --mode raw-data --json 2>/dev/null | sed -n 's/.*"total_size":\([0-9]*\).*/\1/p' || echo 0)"
  tmp="${TEXTFILE}.$$"
  {
    echo "# HELP backup_last_run_timestamp_seconds Unix time the last backup finished."
    echo "# TYPE backup_last_run_timestamp_seconds gauge"
    echo "backup_last_run_timestamp_seconds ${now}"
    echo "# HELP backup_last_run_success 1 if the last backup succeeded."
    echo "# TYPE backup_last_run_success gauge"
    echo "backup_last_run_success ${ok}"
    [ "$ok" = "1" ] && { echo "# HELP backup_last_success_timestamp_seconds Unix time of the last SUCCESSFUL backup."; echo "# TYPE backup_last_success_timestamp_seconds gauge"; echo "backup_last_success_timestamp_seconds ${now}"; }
    echo "# HELP backup_last_run_duration_seconds Duration of the last backup."
    echo "# TYPE backup_last_run_duration_seconds gauge"
    echo "backup_last_run_duration_seconds ${dur}"
    echo "# HELP backup_snapshots Number of snapshots in the repository."
    echo "# TYPE backup_snapshots gauge"
    echo "backup_snapshots ${snaps:-0}"
    echo "# HELP backup_repository_bytes Raw data size of the repository."
    echo "# TYPE backup_repository_bytes gauge"
    echo "backup_repository_bytes ${size:-0}"
  } > "$tmp" && mv "$tmp" "$TEXTFILE"
}

if ! restic snapshots >/dev/null 2>&1; then
  echo "[backup] initialising repository at ${RESTIC_REPOSITORY}"
  restic init
fi

run_once() {
  start="$(date +%s)"
  if restic backup --host fritz-monitoring --tag auto $PATHS \
       --exclude '**/.git' --exclude '**/wal' --exclude '**/*.tmp'; then
    restic forget --prune $KEEP --tag auto || echo "[backup] prune failed (non-fatal)"
    write_metrics 1 "$(( $(date +%s) - start ))"
    echo "[backup] ok in $(( $(date +%s) - start ))s"
  else
    write_metrics 0 "$(( $(date +%s) - start ))"
    echo "[backup] FAILED" >&2
  fi
}

if [ "${1:-loop}" = "once" ]; then
  run_once
  exit 0
fi

echo "[backup] loop: every ${INTERVAL_HOURS}h, repo ${RESTIC_REPOSITORY}"
while true; do
  run_once
  sleep "$(( INTERVAL_HOURS * 3600 ))"
done
