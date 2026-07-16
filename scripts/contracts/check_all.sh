#!/usr/bin/env bash
# Runs every contract gate against a running stack (default: local compose stack).
# Usage: check_all.sh [host] [report_dir]
set -euo pipefail

HOST="${1:-localhost}"
REPORT_DIR="${2:-contract-reports}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts/contracts"
source "$SCRIPTS/services.sh"

mkdir -p "$REPORT_DIR"
status=0

bash "$SCRIPTS/check_proto.sh" | tee "$REPORT_DIR/proto.txt" || status=1
python3 "$SCRIPTS/check_events.py" ${CHECK_EVENTS_ARGS:-} | tee "$REPORT_DIR/events.txt" || status=1

for entry in "${SERVICES[@]}"; do
  IFS=: read -r name port has_swagger <<<"$entry"
  if [ "$has_swagger" = "yes" ]; then
    python3 "$SCRIPTS/check_openapi.py" "$name" "http://$HOST:$port" \
      --report "$REPORT_DIR/openapi-$name.md" || status=1
  fi
  python3 "$SCRIPTS/check_health.py" "$name" "http://$HOST:$port" \
    | tee "$REPORT_DIR/health-$name.txt" || status=1
done

bash "$SCRIPTS/check_db_schema.sh" "$REPORT_DIR" || status=1

if [ $status -ne 0 ]; then
  echo "One or more contract gates FAILED. See $REPORT_DIR/."
  exit 1
fi
echo "All contract gates passed."
