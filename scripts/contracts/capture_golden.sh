#!/usr/bin/env bash
# Captures every golden contract artifact from the running .NET reference stack
# into contracts/. Run scripts/contracts/run_stack.sh first (or CI equivalent).
#
# Usage: scripts/contracts/capture_golden.sh [host]
set -euo pipefail

HOST="${1:-localhost}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTRACTS="$REPO_ROOT/contracts"
SCRIPTS="$REPO_ROOT/scripts/contracts"
source "$SCRIPTS/services.sh"

SQL_CONTAINER="${SQL_CONTAINER:-src-sqldata-1}"
MONGO_CONTAINER="${MONGO_CONTAINER:-src-nosqldata-1}"
SA_PASSWORD="${SA_PASSWORD:-Pass@word}"

mkdir -p "$CONTRACTS"/{openapi,health,proto,db,events}

echo "== OpenAPI documents =="
for entry in "${SERVICES[@]}"; do
  IFS=: read -r name port has_swagger <<<"$entry"
  if [ "$has_swagger" = "yes" ]; then
    curl -fsS "http://$HOST:$port/swagger/v1/swagger.json" \
      | python3 -m json.tool --no-ensure-ascii > "$CONTRACTS/openapi/$name.swagger.json"
    echo "  captured $name"
  fi
done

echo "== Health goldens =="
for entry in "${SERVICES[@]}"; do
  IFS=: read -r name port _ <<<"$entry"
  curl -fsS "http://$HOST:$port/hc" | python3 "$SCRIPTS/normalize_hc.py" \
    > "$CONTRACTS/health/$name.hc.golden.json"
  curl -fsS "http://$HOST:$port/liveness" > "$CONTRACTS/health/$name.liveness.golden.txt"
  echo "  captured $name"
done

echo "== Proto contracts =="
cp "$REPO_ROOT/src/Services/Basket/Basket.API/Proto/basket.proto" "$CONTRACTS/proto/"
cp "$REPO_ROOT/src/Services/Catalog/Catalog.API/Proto/catalog.proto" "$CONTRACTS/proto/"
cp "$REPO_ROOT/src/Services/Ordering/Ordering.API/Proto/ordering.proto" "$CONTRACTS/proto/"
(cd "$REPO_ROOT" && sha256sum \
  src/Services/Basket/Basket.API/Proto/basket.proto \
  src/Services/Catalog/Catalog.API/Proto/catalog.proto \
  src/Services/Ordering/Ordering.API/Proto/ordering.proto \
  > "$CONTRACTS/proto/checksums.sha256")

echo "== SQL schema dumps =="
declare -A SQL_DBS=(
  [catalog]="Microsoft.eShopOnContainers.Services.CatalogDb"
  [ordering]="Microsoft.eShopOnContainers.Services.OrderingDb"
  [marketing]="Microsoft.eShopOnContainers.Services.MarketingDb"
  [webhooks]="Microsoft.eShopOnContainers.Services.WebhooksDb"
  [identity]="Microsoft.eShopOnContainers.Service.IdentityDb"
)
docker cp "$SCRIPTS/sql_schema_dump.sql" "$SQL_CONTAINER:/tmp/sql_schema_dump.sql"
for svc in catalog ordering marketing webhooks identity; do
  docker exec "$SQL_CONTAINER" /opt/mssql-tools/bin/sqlcmd \
    -S localhost -U sa -P "$SA_PASSWORD" -d "${SQL_DBS[$svc]}" \
    -i /tmp/sql_schema_dump.sql -W -s "|" -h -1 \
    > "$CONTRACTS/db/$svc.sqlschema.txt"
  echo "  captured $svc"
done

echo "== Mongo schema dumps =="
MONGO_SHELL="mongosh"
docker exec "$MONGO_CONTAINER" which mongosh >/dev/null 2>&1 || MONGO_SHELL="mongo"
docker cp "$SCRIPTS/mongo_schema_dump.js" "$MONGO_CONTAINER:/tmp/mongo_schema_dump.js"
for db in MarketingDb LocationsDb; do
  docker exec "$MONGO_CONTAINER" "$MONGO_SHELL" --quiet "$db" /tmp/mongo_schema_dump.js \
    > "$CONTRACTS/db/${db,,}.mongoschema.txt"
  echo "  captured $db"
done

echo "== Golden integration events (Newtonsoft.Json) =="
docker run --rm -v "$REPO_ROOT:/repo" -w /repo/src \
  mcr.microsoft.com/dotnet/core/sdk:3.1 \
  dotnet run --project Tests/Contracts/EventContractsGenerator -c Release -- /repo/contracts/events

echo "All golden artifacts captured under contracts/."
