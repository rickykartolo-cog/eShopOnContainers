# eshop_common — shared Python foundation

Reusable, pip-installable package that every migrated Python (FastAPI) service in
the eShopOnContainers strangler-fig migration consumes. It preserves the frozen
contracts of the .NET building blocks; see `docs/devin-modernization-prompt.md`
(master prompt §3) for the specification.

## Capabilities

- **`eshop_common.config`** — case-insensitive settings honoring the exact
  compose environment-variable interface (`ConnectionString`, `EventBusConnection`,
  `identityUrl`/`IdentityUrl`, `PORT`, `GRPC_PORT`, ...); fails fast with redacted errors.
- **`eshop_common.events`** — `IntegrationEvent` base (`Id` GUID + `CreationDate`
  UTC) with byte-exact Newtonsoft.Json-compatible serialization (golden captured
  from Newtonsoft.Json 12.0.3 on netcoreapp3.1: `docs/golden/`).
- **`eshop_common.eventbus`** — one typed interface with two adapters:
  - RabbitMQ (`aio-pika`): direct exchange `eshop_event_bus`, routing key =
    event class name, persistent messages, durable service queue, retry/reconnect.
  - Azure Service Bus (`azure-servicebus`): Label/Subject = class name without
    the `IntegrationEvent` suffix, per-event correlation-filter rules.
- **`eshop_common.outbox`** — transactional outbox on the unchanged
  `IntegrationEventLog` schema and states (`NotPublished`, `InProgress`,
  `Published`, `PublishedFailed`), plus an additive event-`Id` inbox for
  consumer deduplication.
- **`eshop_common.health`** — `/liveness` (self only) and `/hc` matching the
  exact `UIResponseWriter.WriteHealthCheckUIResponse` JSON shape (golden
  captured from a running netcoreapp3.1 service: `docs/golden/hc-*.json`);
  adapters for SQL Server, MongoDB, Redis, RabbitMQ, Azure Service Bus, and HTTP URLs.
- **`eshop_common.auth`** — JWT validation via OIDC discovery + rotating JWKS
  with exact audience validation (`basket`, `orders`, `marketing`, `locations`,
  `orders.signalrhub`, `webhooks`, `mobileshoppingagg`, `webshoppingagg`).
- **`eshop_common.observability`** — structlog with secret redaction and
  correlation IDs; OpenTelemetry instrumentation for FastAPI/HTTPX.
- **`eshop_common.template`** — service factory with startup/shutdown hooks,
  exception mapping (400 for validation errors, ASP.NET-style), OpenAPI at
  `/swagger/v1/swagger.json`, separate HTTP (`PORT`=80) and gRPC (`GRPC_PORT`=81)
  listeners.
- **`eshop_common.testing`** — pytest fixtures against the standard test
  dependency images.

## Install

```bash
cd src/python/eshop_common
pip install -e ".[dev]"
```

SQL Server access additionally requires the Microsoft ODBC Driver 18
(`msodbcsql18`); validated versions are pinned in `docs/odbc-validation.md`.

## Test

Unit tests (no external dependencies):

```bash
pytest tests/unit -v
```

Full suite including integration tests via docker compose (uses the same
dependency images as `src/docker-compose-tests.yml`):

```bash
docker compose -f docker-compose-tests.yml up --build --abort-on-container-exit --exit-code-from eshop-common-tests
```

Or against locally running dependencies (endpoints overridable via
`TEST_SQL_HOST`, `TEST_RABBITMQ_HOST`, `TEST_REDIS_URL`, `TEST_MONGO_URL`):

```bash
pytest tests -v
```

Lint:

```bash
ruff check eshop_common tests
```
