# SQL Server async path validation (aioodbc + pyodbc + ODBC Driver 18)

Validated 2026-07-16 against `mcr.microsoft.com/mssql/server:2017-latest`
(Microsoft SQL Server 2017 RTM-CU31-GDR, KB5102337, 14.0.3540.1 X64) on
Ubuntu 22.04 x86_64.

## Validated versions (pinned for reproducibility)

| Component | Version |
| --- | --- |
| CPython | 3.12.13 |
| pyodbc | 5.3.0 |
| aioodbc | 0.5.0 |
| SQLAlchemy (async, `mssql+aioodbc` dialect) | 2.0.51 |
| Microsoft ODBC Driver 18 for SQL Server (`msodbcsql18`) | 18.6.2.1-1 |
| unixODBC | 2.3.9 |

## What was validated

1. Raw `aioodbc` async connect + `SELECT @@VERSION` and typed result rows
   (INT, NVARCHAR, DECIMAL(18,2), UNIQUEIDENTIFIER, DATETIME2).
2. SQLAlchemy 2 async engine (`mssql+aioodbc://...?driver=ODBC+Driver+18+for+SQL+Server`)
   DDL + DML round trip using the `IntegrationEventLog`-style column types.
3. 10 concurrent async queries through the pooled async engine.
4. Transaction rollback semantics (see `tests/integration/test_sqlserver_odbc.py`,
   which re-runs this validation as part of the suite).

## Connection-string notes

- ODBC Driver 18 defaults to `Encrypt=yes`; SQL Server 2017 in the dev/test
  containers has no trusted certificate, so connections require
  `Encrypt=Optional` (or `TrustServerCertificate=yes`). The compose-era .NET
  services used driver defaults that did not force encryption; keep
  `Encrypt=Optional;TrustServerCertificate=yes` for parity in dev/test
  topologies only.
- The async dialect name is `mssql+aioodbc`; pass the driver via the
  `driver=ODBC+Driver+18+for+SQL+Server` query parameter.

## Repro command

```bash
docker run -d --name mssql-test -e ACCEPT_EULA=Y -e SA_PASSWORD='Pass@word' -p 1433:1433 mcr.microsoft.com/mssql/server:2017-latest
pip install "pyodbc==5.3.0" "aioodbc==0.5.0" "sqlalchemy==2.0.51"
pytest tests/integration/test_sqlserver_odbc.py -m integration -v
```
