#!/usr/bin/env bash
# P1 — flag weak / placeholder / reused secrets. Non-fatal by default; pass
# --strict to exit non-zero on any finding (used in CI).
set -euo pipefail
cd "$(dirname "$0")/.."

STRICT="${1:-}"
WEAK_RE='^(test|test_password|test_secret_key|changeme|change-me|password|passwd|secret|admin|grafana|fritzbox|123|abc)'
MIN_LEN=16
findings=0
seen_hashes=""

note() { printf '\033[1;33m  ⚠ %s\033[0m\n' "$*"; findings=$((findings + 1)); }

echo "Checking secrets/*.txt …"
shopt -s nullglob
for f in secrets/*.txt; do
  [ -f "$f" ] || continue
  v="$(tr -d '\n' < "$f")"
  n="$(basename "$f")"
  len=${#v}
  [ "$len" -lt "$MIN_LEN" ] && note "$n: only $len chars (want >= $MIN_LEN)"
  printf '%s' "$v" | grep -qiE "$WEAK_RE" && note "$n: looks like a placeholder / weak value"
  h="$(printf '%s' "$v" | shasum -a 256 | cut -d' ' -f1)"
  if printf '%s\n' "$seen_hashes" | grep -q "^$h "; then
    other="$(printf '%s\n' "$seen_hashes" | sed -n "s/^$h //p" | head -1)"
    note "$n: same value as $other (secret reuse)"
  else
    seen_hashes="$seen_hashes
$h $n"
  fi
done

if [ -f .env.production ]; then
  if grep -qE '^(TIBBER_TOKEN|NTFY_TOKEN|B2_ACCOUNT_KEY|AWS_SECRET_ACCESS_KEY|BLINK_PASSWORD)=[^/[:space:]].{6,}' .env.production; then
    note ".env.production has a literal token/password — prefer a /secrets file path"
  fi
fi

if [ "$findings" -eq 0 ]; then
  printf '\033[1;32m  ✓ no weak or reused secrets\033[0m\n'
  exit 0
fi
echo "$findings finding(s)."
[ "$STRICT" = "--strict" ] && exit 1 || exit 0
