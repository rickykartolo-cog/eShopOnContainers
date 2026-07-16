#!/usr/bin/env bash
# Per-service contract gate: builds and starts one .NET service (plus its
# data/broker dependencies) using the repo's Compose files, then runs the
# OpenAPI, health, and database contract checks against it.
#
# Usage: gate_service.sh <service> [report_dir]
#   service ∈ basket catalog identity locations marketing ordering
#             ordering-signalrhub payment webhooks
#
# Set EXTRA_COMPOSE_FILE to layer an additional compose file (e.g.
# docker-compose-catalog-python.override.yml) to gate a migrated candidate
# implementation against the same frozen contracts.
set -euo pipefail

SERVICE="$1"
REPORT_DIR="${2:-contract-reports/$SERVICE}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts/contracts"
source "$SCRIPTS/services.sh"

export ESHOP_EXTERNAL_DNS_NAME_OR_IP="${ESHOP_EXTERNAL_DNS_NAME_OR_IP:-localhost}"
export ESHOP_PROD_EXTERNAL_DNS_NAME_OR_IP="${ESHOP_PROD_EXTERNAL_DNS_NAME_OR_IP:-localhost}"

declare -A COMPOSE_NAME=(
  [basket]=basket-api [catalog]=catalog-api [identity]=identity-api
  [locations]=locations-api [marketing]=marketing-api [ordering]=ordering-api
  [ordering-signalrhub]=ordering-signalrhub [payment]=payment-api [webhooks]=webhooks-api
)
declare -A DEPS=(
  [basket]="basketdata rabbitmq identity-api sqldata"
  [catalog]="sqldata rabbitmq"
  [identity]="sqldata"
  [locations]="nosqldata rabbitmq identity-api sqldata"
  [marketing]="sqldata nosqldata rabbitmq identity-api"
  [ordering]="sqldata rabbitmq identity-api"
  [ordering-signalrhub]="rabbitmq identity-api sqldata"
  [payment]="rabbitmq"
  [webhooks]="sqldata rabbitmq identity-api"
)

PORT=""
HAS_SWAGGER=""
for entry in "${SERVICES[@]}"; do
  IFS=: read -r name port has_swagger <<<"$entry"
  if [ "$name" = "$SERVICE" ]; then PORT="$port"; HAS_SWAGGER="$has_swagger"; fi
done
[ -n "$PORT" ] || { echo "unknown service: $SERVICE"; exit 2; }

cd "$REPO_ROOT/src"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.override.yml)
[ -n "${EXTRA_COMPOSE_FILE:-}" ] && COMPOSE_FILES+=(-f "$EXTRA_COMPOSE_FILE")
# shellcheck disable=SC2086
docker compose "${COMPOSE_FILES[@]}" build \
  "${COMPOSE_NAME[$SERVICE]}" ${DEPS[$SERVICE]}
# shellcheck disable=SC2086
docker compose "${COMPOSE_FILES[@]}" up -d \
  "${COMPOSE_NAME[$SERVICE]}" ${DEPS[$SERVICE]}

echo "Waiting for $SERVICE to report healthy on port $PORT..."
healthy=0
for _ in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/hc" || true)
  if [ "$code" = "200" ]; then healthy=1; break; fi
  sleep 5
done
if [ "$healthy" != "1" ]; then
  echo "$SERVICE never became healthy"
  docker compose "${COMPOSE_FILES[@]}" logs "${COMPOSE_NAME[$SERVICE]}" | tail -100
  exit 1
fi

mkdir -p "$REPO_ROOT/$REPORT_DIR"
status=0
if [ "$HAS_SWAGGER" = "yes" ]; then
  python3 "$SCRIPTS/check_openapi.py" "$SERVICE" "http://localhost:$PORT" \
    --report "$REPO_ROOT/$REPORT_DIR/openapi-$SERVICE.md" || status=1

  # Human-readable breaking-change report via openapi-diff.
  curl -fsS "http://localhost:$PORT/swagger/v1/swagger.json" > "$REPO_ROOT/$REPORT_DIR/$SERVICE.live.swagger.json"
  docker run --rm -v "$REPO_ROOT:/specs" openapitools/openapi-diff:2.0.1 \
    "/specs/contracts/openapi/$SERVICE.swagger.json" \
    "/specs/$REPORT_DIR/$SERVICE.live.swagger.json" \
    --markdown "/specs/$REPORT_DIR/openapi-diff-$SERVICE.md" --fail-on-changed || status=1
fi
python3 "$SCRIPTS/check_health.py" "$SERVICE" "http://localhost:$PORT" \
  | tee "$REPO_ROOT/$REPORT_DIR/health-$SERVICE.txt" || status=1
bash "$SCRIPTS/check_db_schema.sh" "$REPO_ROOT/$REPORT_DIR" "$SERVICE" || status=1

if [ $status -ne 0 ]; then
  echo "Contract gate FAILED for $SERVICE. Reports in $REPORT_DIR/."
  exit 1
fi
echo "Contract gate passed for $SERVICE."
