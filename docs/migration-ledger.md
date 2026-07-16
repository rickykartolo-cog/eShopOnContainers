# Migration Ledger — eShopOnContainers .NET → Python (strangler fig)

Baseline: `.NET Core 3.1 / Angular 8` at `origin/main` commit
`31ab9b62b9fb02fb1c1eb7cadef285c5e6ca6731`. Master specification:
`docs/devin-modernization-prompt.md`. This ledger is the single source of truth
for migration state; update it in the same PR as any cutover-affecting change.

## Reproducing the current stack

Verified commands (Docker 27.x / Compose v2):

```bash
cd src
export ESHOP_EXTERNAL_DNS_NAME_OR_IP=localhost
export ESHOP_PROD_EXTERNAL_DNS_NAME_OR_IP=localhost

docker compose -f docker-compose.yml -f docker-compose.override.yml build \
  sqldata nosqldata basketdata rabbitmq identity-api basket-api catalog-api \
  ordering-api ordering-backgroundtasks ordering-signalrhub marketing-api \
  payment-api locations-api webhooks-api

docker compose -f docker-compose.yml -f docker-compose.override.yml up -d \
  sqldata nosqldata basketdata rabbitmq identity-api basket-api catalog-api \
  ordering-api ordering-backgroundtasks ordering-signalrhub marketing-api \
  payment-api locations-api webhooks-api
```

Or simply `scripts/contracts/run_stack.sh` (adds health-based readiness waits —
services report `/hc` 200 only after SQL/Mongo seeding completes, ~60–90 s).

Functional-test harness (unchanged): `src/docker-compose-tests.yml` +
`src/docker-compose-tests.override.yml` (SQL Server 2017, MongoDB, Redis,
RabbitMQ test topology).

### Workarounds required at this baseline

1. **Identity.API LibMan restore failure**: the pinned
   `Microsoft.Web.LibraryManager.Build 2.0.96` can no longer resolve `cdnjs`
   (API change) or `unpkg`, breaking `docker compose build identity-api`.
   Fixed in this slice by bumping to `2.1.175` and moving the `bootstrap@4.1.3`
   library to the `jsdelivr` provider (build tooling only; served asset paths
   under `wwwroot/lib/` are unchanged).
2. Compose `version:` attribute warnings from Compose v2 are benign.

## Ledger

Ports = host ports from `src/docker-compose.override.yml`. Rollback (once a
Python candidate is deployed) is configuration-only: repoint the Compose service
image back to the .NET image and `up -d` that one service — for example
`REGISTRY=eshop TAG=linux-latest docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --no-build <service>`.

| Service | Owner path | Compose name / ports | Contract snapshots | Test suites | Current image | Replacement image | Cutover status | Rollback command |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Basket | `src/Services/Basket/Basket.API` | `basket-api` 5103:80, 9103:81 | `contracts/openapi/basket.swagger.json`; `contracts/proto/basket.proto`; events: UserCheckoutAccepted (prod), ProductPriceChanged, OrderStarted (cons); `contracts/health/basket.*`; `contracts/auth` (aud `basket`) | `Basket.FunctionalTests`, `Basket.UnitTests` under `src/Services/Basket`; app scenarios in `src/Tests/Services/Application.FunctionalTests` | `eshop/basket.api:linux-latest` | _none yet_ | contracts-frozen | `docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --no-build basket-api` |
| Catalog | `src/Services/Catalog/Catalog.API` | `catalog-api` 5101:80, 9101:81 | `contracts/openapi/catalog.swagger.json`; `contracts/proto/catalog.proto`; events: ProductPriceChanged, OrderStockConfirmed/Rejected (prod), OrderStatusChangedToAwaitingValidation/Paid (cons); `contracts/db/catalog.sqlschema.txt` (HiLo `catalog_hilo`, `catalog_brand_hilo`, `catalog_type_hilo`); `contracts/health/catalog.*`; anonymous (no JWT) | `Catalog.FunctionalTests`, `Catalog.UnitTests`; app scenarios | `eshop/catalog.api:linux-latest` | `eshop/catalog.api.python:linux-latest` (`src/python/catalog_api`, built via `src/docker-compose-catalog-python.override.yml`) | candidate-ready (Python FastAPI implementation + tests + CI gate in place; .NET image remains the default) | `docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --no-build catalog-api` |
| Identity | `src/Services/Identity/Identity.API` | `identity-api` 5105:80 | No OpenAPI (404 by design); `contracts/db/identity.sqlschema.txt`; `contracts/health/identity.*`; clients/scopes in `contracts/auth/auth-requirements.md` | none in baseline; manual login flows + future IdP migration reconciliation tests | `eshop/identity.api:linux-latest` | External OIDC IdP (Keycloak 26.x preferred — decision locked, no Python rewrite) | contracts-frozen | `docker compose ... up -d --no-build identity-api` |
| Location | `src/Services/Location/Locations.API` | `locations-api` 5109:80 | `contracts/openapi/locations.swagger.json`; event UserLocationUpdated (prod); `contracts/db/locationsdb.mongoschema.txt` (incl. `2dsphere`); `contracts/health/locations.*`; aud `locations` | `Locations.FunctionalTests` under `src/Services/Location`; app scenarios | `eshop/locations.api:linux-latest` | `eshop/locations.api.python:linux-latest` (`src/python/locations_api`, built via `src/docker-compose-locations-python.override.yml`) | candidate-ready (Python FastAPI implementation + tests + CI gate in place; .NET image remains the default) | `docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --no-build locations-api` |
| Marketing | `src/Services/Marketing/Marketing.API` | `marketing-api` 5110:80 | `contracts/openapi/marketing.swagger.json`; event UserLocationUpdated (cons); `contracts/db/marketing.sqlschema.txt` (SQL write model) + `contracts/db/marketingdb.mongoschema.txt` (Mongo read model, empty at seed); `contracts/health/marketing.*`; aud `marketing` | `Marketing.FunctionalTests/CampaignScenarios`; app scenarios | `eshop/marketing.api:linux-latest` | _none yet_ | contracts-frozen | `docker compose ... up -d --no-build marketing-api` |
| Ordering.API | `src/Services/Ordering/Ordering.API` | `ordering-api` 5102:80, 9102:81 | `contracts/openapi/ordering.swagger.json`; `contracts/proto/ordering.proto`; events: OrderStarted + 6 status events (prod), UserCheckoutAccepted/GracePeriodConfirmed/OrderStockConfirmed/Rejected/OrderPaymentSucceeded/Failed (cons); `contracts/db/ordering.sqlschema.txt` (schema `ordering`, HiLo `ordering.orderseq`/`buyerseq`/`paymentseq`, dbo `orderitemseq`, owned `Address_*`); `contracts/health/ordering.*`; aud `orders` | `Ordering.FunctionalTests` (`OrderingScenarioBase`), `Ordering.UnitTests`; app scenarios | `eshop/ordering.api:linux-latest` | _none yet_ | contracts-frozen (migrate late) | `docker compose ... up -d --no-build ordering-api` |
| Ordering.BackgroundTasks | `src/Services/Ordering/Ordering.BackgroundTasks` | `ordering-backgroundtasks` 5111:80 | event GracePeriodConfirmed (prod), golden in `contracts/events/` | none (behavioral: grace-period publication) | `eshop/ordering.backgroundtasks:linux-latest` | _none yet_ (retain until Ordering migrates) | contracts-frozen | `docker compose ... up -d --no-build ordering-backgroundtasks` |
| Ordering.SignalrHub | `src/Services/Ordering/Ordering.SignalrHub` | `ordering-signalrhub` 5112:80 | No OpenAPI; realtime contract `/hub/notificationhub`, `UpdatedOrderState {OrderId, Status}`; consumes 6 order-status events; `contracts/health/ordering-signalrhub.*`; aud `orders.signalrhub` | none (add e2e realtime tests before protocol change) | `eshop/ordering.signalrhub:linux-latest` | _none yet_ (migrate last, gated with frontend) | contracts-frozen | `docker compose ... up -d --no-build ordering-signalrhub` |
| Payment | `src/Services/Payment/Payment.API` | `payment-api` 5108:80 | No OpenAPI (no HTTP API); events OrderPaymentSucceeded/Failed (prod), OrderStatusChangedToStockConfirmed (cons); `contracts/health/payment.*` | none in baseline — author new tests from frozen events | `eshop/payment.api:linux-latest` | _none yet_ | contracts-frozen | `docker compose ... up -d --no-build payment-api` |
| Webhooks | `src/Services/Webhooks/Webhooks.API` | `webhooks-api` 5113:80 | `contracts/openapi/webhooks.swagger.json`; events ProductPriceChanged/OrderStatusChangedToShipped/Paid (cons); `contracts/db/webhooks.sqlschema.txt`; `contracts/health/webhooks.*`; aud `webhooks` | none in baseline — author new HTTP tests from frozen OpenAPI | `eshop/webhooks.api:linux-latest` | _none yet_ | contracts-frozen | `docker compose ... up -d --no-build webhooks-api` |

### Unchanged-by-this-plan components (tracked for completeness)

| Component | Owner path | Notes |
| --- | --- | --- |
| Envoy gateways | `src/ApiGateways/Envoy` | Route contracts preserved throughout migration. |
| HttpAggregators (BFFs) | `src/ApiGateways/*/aggregator` | Audiences `mobileshoppingagg`/`webshoppingagg`; port only if fully-Python end state required. |
| WebSPA | `src/Web/WebSPA` | Angular modernized in place (decision locked); service name `webspa`, port 5104. |
| WebMVC / WebStatus / WebhookClient | `src/Web/*` | Consume frozen contracts; WebStatus polls `/hc`. |

## Contract gates (CI)

`.github/workflows/contract-gates.yml`:

- `static-contracts`: proto checksum/diff, golden event regeneration
  (byte-for-byte, via the .NET 3.1 SDK container), JSON Schema validation and
  regenerability.
- `service-contract-gate (<service>)`: per-service required gate — builds the
  .NET service with the repo Compose files, waits for `/hc` healthy, then runs
  OpenAPI exact+semantic diff, `openapi-diff` breaking-change report, health
  golden comparison, and SQL/Mongo schema diff. Human-readable diffs are
  uploaded as CI artifacts (`contract-reports-<service>`).

A Python candidate replaces a service only when the same gates pass against the
candidate (point `gate_service.sh` at the candidate's compose service) and the
mixed-stack event/round-trip tests from master prompt §6 are green.

Catalog-specific jobs added with the Python candidate:

- `catalog-python-unit`: ruff lint plus the pytest suite under
  `src/python/catalog_api/tests` (HTTP functional oracle port, gRPC parity,
  event-golden serialization, outbox atomicity, duplicate-delivery idempotency,
  OpenAPI golden equality, health golden shape, proto-freeze checksum).
- `catalog-python-contract-gate`: runs the existing `gate_service.sh catalog`
  with `EXTRA_COMPOSE_FILE=docker-compose-catalog-python.override.yml`, so the
  Python container is held to the same frozen OpenAPI/health/DB-schema gates as
  the .NET service.

Locations-specific jobs added with the Python candidate:

- `locations-python-unit`: ruff lint plus the pytest suite under
  `src/python/locations_api/tests` (HTTP functional oracle port, event-golden
  serialization, OpenAPI golden equality, health golden shape) and the
  integration markers on real dependencies: Mongo parity per master prompt §6.4
  (seed schema/index diff vs the frozen dump, `$near`/`$geoIntersects` oracle
  queries, bidirectional .NET↔Python document round-trips) and the RabbitMQ
  mixed-stack wire test (Marketing-style binding on `eshop_event_bus`, routing
  key `UserLocationUpdatedIntegrationEvent`, frozen JSON body).
- `locations-python-contract-gate`: runs the existing `gate_service.sh locations`
  with `EXTRA_COMPOSE_FILE=docker-compose-locations-python.override.yml`, so the
  Python container is held to the same frozen OpenAPI/health/Mongo-schema gates
  as the .NET service.

## Catalog cutover runbook (Python candidate)

The Python implementation lives in `src/python/catalog_api` and reuses
`src/python/eshop_common`. Same compose service name (`catalog-api`), ports
(5101:80 HTTP, 9101:81 gRPC), environment variables, database, and event
contracts.

Shadow deploy (build + run the Python candidate in the full stack):

```
cd src
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose-catalog-python.override.yml build catalog-api
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose-catalog-python.override.yml up -d
```

The Python service runs against the database created/seeded by the .NET
migrations without destructive changes (it only creates the schema when the
database is empty, mirroring the EF migrations).

Cutover = the same `up -d` layered command (the override swaps only the
`catalog-api` image). One-step rollback to .NET:

```
cd src
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --no-build catalog-api
```

## Location cutover runbook (Python candidate)

The Python implementation lives in `src/python/locations_api` and reuses
`src/python/eshop_common`. Same compose service name (`locations-api`), port
(5109:80), environment variables (`ConnectionString`, `Database`, `identityUrl`,
`IdentityUrlExternal`, `EventBus*`, `PATH_BASE=/locations-api`), MongoDB
collections (`Locations`, `UserLocation`, `Location_2dsphere` index), and the
`UserLocationUpdatedIntegrationEvent` contract consumed by Marketing.

Shadow deploy (build + run the Python candidate in the full stack):

```
cd src
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose-locations-python.override.yml build locations-api
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose-locations-python.override.yml up -d
```

The Python service runs against the LocationsDb seeded by either
implementation without destructive changes (it seeds only when the `Locations`
collection is empty, mirroring `LocationsContextSeed`), and its `UserLocation`
upserts are readable by the .NET driver (verified by the bidirectional
round-trip tests).

Cutover = the same `up -d` layered command (the override swaps only the
`locations-api` image). One-step rollback to .NET:

```
cd src
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --no-build locations-api
```
