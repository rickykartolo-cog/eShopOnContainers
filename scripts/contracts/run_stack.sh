#!/usr/bin/env bash
# Builds and starts the .NET reference backend stack used for contract capture/checks.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT/src"

export ESHOP_EXTERNAL_DNS_NAME_OR_IP="${ESHOP_EXTERNAL_DNS_NAME_OR_IP:-localhost}"
export ESHOP_PROD_EXTERNAL_DNS_NAME_OR_IP="${ESHOP_PROD_EXTERNAL_DNS_NAME_OR_IP:-localhost}"

BACKEND_SERVICES=(sqldata nosqldata basketdata rabbitmq identity-api basket-api catalog-api
  ordering-api ordering-backgroundtasks ordering-signalrhub marketing-api payment-api
  locations-api webhooks-api)

docker compose -f docker-compose.yml -f docker-compose.override.yml build "${BACKEND_SERVICES[@]}"
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d "${BACKEND_SERVICES[@]}"

echo "Waiting for services to become healthy..."
for port in 5101 5102 5103 5105 5108 5109 5110 5112 5113; do
  for _ in $(seq 1 60); do
    if curl -fsS "http://localhost:$port/liveness" >/dev/null 2>&1; then
      echo "  port $port live"
      break
    fi
    sleep 5
  done
done

# /hc turns Healthy only after DB seeding completes; wait for it.
for port in 5101 5102 5103 5105 5108 5109 5110 5112 5113; do
  for _ in $(seq 1 60); do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port/hc")
    if [ "$code" = "200" ]; then
      echo "  port $port healthy"
      break
    fi
    sleep 5
  done
done
