# Frozen contract artifacts

Golden contract artifacts captured from the .NET Core 3.1 reference stack at
`origin/main` commit `31ab9b62b9fb02fb1c1eb7cadef285c5e6ca6731`. These freeze the
externally observable behavior of every backend service and are the merge/cutover
gate for Python (FastAPI) replacements. **Do not edit these files by hand** —
regenerate them with the documented scripts and review any diff as a contract change.

## Layout

| Path | Contents |
| --- | --- |
| `openapi/<service>.swagger.json` | `/swagger/v1/swagger.json` from each running .NET service (pretty-printed, otherwise byte-faithful). Identity, Payment, and Ordering.SignalrHub expose no OpenAPI document (404) by design. |
| `proto/*.proto`, `proto/checksums.sha256` | Byte-frozen copies and SHA-256 checksums of the three gRPC contracts (basket, catalog, ordering). |
| `events/<Event>.golden.json` | Golden Newtonsoft.Json serialization of each of the 15 integration events, produced by the exact producer classes via `src/Tests/Contracts/EventContractsGenerator` (deterministic pinned `Id`/`CreationDate`). RabbitMQ routing key = event class name, exchange `eshop_event_bus`; Azure Service Bus label = class name without `IntegrationEvent` suffix. |
| `events/<Event>.schema.json` | JSON Schema (draft-07) snapshots derived from the goldens; all properties required, `additionalProperties: false`. |
| `db/<service>.sqlschema.txt` | Deterministic SQL Server metadata dumps (columns, types, precision, nullability, defaults, PK/unique, indexes, FKs + delete behavior, check constraints, sequences incl. HiLo). |
| `db/*.mongoschema.txt` | MongoDB collections, indexes (incl. `2dsphere` geospatial), and BSON field types. `marketingdb` is empty at baseline seed — its read model is populated only via events at runtime. |
| `health/<service>.hc.golden.json` | Golden `/hc` responses (exact `UIResponseWriter` shape, durations normalized to `<duration>`). |
| `health/<service>.liveness.golden.txt` | Golden `/liveness` bodies. |
| `auth/auth-requirements.md` | JWT authority/audience per service, protected routes, IdP clients/scopes, idempotency headers. |

## Regenerating

```bash
scripts/contracts/run_stack.sh        # build + start the .NET reference stack
scripts/contracts/capture_golden.sh   # re-capture every artifact into contracts/
python3 scripts/contracts/generate_event_schemas.py contracts/events
```

## Verifying (contract gates)

```bash
scripts/contracts/check_all.sh                    # everything, against local stack
scripts/contracts/gate_service.sh <service>       # per-service gate (used by CI)
scripts/contracts/check_proto.sh                  # proto checksums/diff only
python3 scripts/contracts/check_events.py         # event goldens + schemas
```

CI: `.github/workflows/contract-gates.yml` runs the static gates plus a required
per-service matrix gate and uploads human-readable diff reports as artifacts.
