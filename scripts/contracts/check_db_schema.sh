#!/usr/bin/env bash
# Database schema contract gate.
# Re-dumps SQL Server and MongoDB schema metadata from the running stack and
# diffs it against the frozen dumps under contracts/db/.
#
# Usage: check_db_schema.sh [report_dir] [service]
# With no service argument, all databases are checked.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts/contracts"
REPORT_DIR="${1:-}"
ONLY_SERVICE="${2:-}"

SQL_CONTAINER="${SQL_CONTAINER:-src-sqldata-1}"
MONGO_CONTAINER="${MONGO_CONTAINER:-src-nosqldata-1}"
SA_PASSWORD="${SA_PASSWORD:-Pass@word}"

declare -A SQL_DBS=(
  [catalog]="Microsoft.eShopOnContainers.Services.CatalogDb"
  [ordering]="Microsoft.eShopOnContainers.Services.OrderingDb"
  [marketing]="Microsoft.eShopOnContainers.Services.MarketingDb"
  [webhooks]="Microsoft.eShopOnContainers.Services.WebhooksDb"
  [identity]="Microsoft.eShopOnContainers.Service.IdentityDb"
)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
status=0

SQL_SERVICES=(catalog ordering marketing webhooks identity)
MONGO_DBS=(MarketingDb LocationsDb)
if [ -n "$ONLY_SERVICE" ]; then
  case "$ONLY_SERVICE" in
    catalog|ordering|webhooks|identity) SQL_SERVICES=("$ONLY_SERVICE"); MONGO_DBS=() ;;
    marketing) SQL_SERVICES=(marketing); MONGO_DBS=(MarketingDb) ;;
    locations) SQL_SERVICES=(); MONGO_DBS=(LocationsDb) ;;
    *) SQL_SERVICES=(); MONGO_DBS=() ;;
  esac
fi

if [ ${#SQL_SERVICES[@]} -gt 0 ]; then
docker cp "$SCRIPTS/sql_schema_dump.sql" "$SQL_CONTAINER:/tmp/sql_schema_dump.sql"
for svc in "${SQL_SERVICES[@]}"; do
  docker exec "$SQL_CONTAINER" /opt/mssql-tools/bin/sqlcmd \
    -S localhost -U sa -P "$SA_PASSWORD" -d "${SQL_DBS[$svc]}" \
    -i /tmp/sql_schema_dump.sql -W -s "|" -h -1 > "$tmp/$svc.sqlschema.txt"
  if ! diff -u "$REPO_ROOT/contracts/db/$svc.sqlschema.txt" "$tmp/$svc.sqlschema.txt" > "$tmp/$svc.sql.diff"; then
    echo "SQL schema drift detected for $svc:"
    cat "$tmp/$svc.sql.diff"
    status=1
  else
    echo "SQL schema unchanged for $svc"
  fi
  [ -n "$REPORT_DIR" ] && mkdir -p "$REPORT_DIR" && cp "$tmp/$svc.sql.diff" "$REPORT_DIR/$svc.sqlschema.diff" || true
done
fi

if [ ${#MONGO_DBS[@]} -gt 0 ]; then
MONGO_SHELL="mongosh"
docker exec "$MONGO_CONTAINER" which mongosh >/dev/null 2>&1 || MONGO_SHELL="mongo"
docker cp "$SCRIPTS/mongo_schema_dump.js" "$MONGO_CONTAINER:/tmp/mongo_schema_dump.js"
for db in "${MONGO_DBS[@]}"; do
  lower="${db,,}"
  docker exec "$MONGO_CONTAINER" "$MONGO_SHELL" --quiet "$db" /tmp/mongo_schema_dump.js > "$tmp/$lower.mongoschema.txt"
  if ! diff -u "$REPO_ROOT/contracts/db/$lower.mongoschema.txt" "$tmp/$lower.mongoschema.txt" > "$tmp/$lower.mongo.diff"; then
    echo "Mongo schema drift detected for $db:"
    cat "$tmp/$lower.mongo.diff"
    status=1
  else
    echo "Mongo schema unchanged for $db"
  fi
  [ -n "$REPORT_DIR" ] && mkdir -p "$REPORT_DIR" && cp "$tmp/$lower.mongo.diff" "$REPORT_DIR/$lower.mongoschema.diff" || true
done
fi

exit $status
