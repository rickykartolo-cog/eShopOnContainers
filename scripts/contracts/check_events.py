#!/usr/bin/env python3
"""Integration-event contract gate.

1. Regenerates golden Newtonsoft.Json examples with the .NET reference producer
   classes (EventContractsGenerator) and diffs them byte-for-byte against the
   committed goldens.
2. Validates every golden example against its committed JSON Schema snapshot
   (property names, casing, types, required base Id/CreationDate).
3. Asserts the routing-key/exchange conventions recorded in each schema.

Usage: check_events.py [--skip-dotnet]
"""
import argparse
import filecmp
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = REPO_ROOT / "contracts" / "events"

EXPECTED_EVENTS = {
    "ProductPriceChangedIntegrationEvent",
    "UserCheckoutAcceptedIntegrationEvent",
    "OrderStartedIntegrationEvent",
    "OrderStatusChangedToSubmittedIntegrationEvent",
    "OrderStatusChangedToAwaitingValidationIntegrationEvent",
    "OrderStockConfirmedIntegrationEvent",
    "OrderStockRejectedIntegrationEvent",
    "OrderStatusChangedToStockConfirmedIntegrationEvent",
    "OrderPaymentSucceededIntegrationEvent",
    "OrderPaymentFailedIntegrationEvent",
    "OrderStatusChangedToPaidIntegrationEvent",
    "OrderStatusChangedToShippedIntegrationEvent",
    "OrderStatusChangedToCancelledIntegrationEvent",
    "GracePeriodConfirmedIntegrationEvent",
    "UserLocationUpdatedIntegrationEvent",
}

GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def validate(instance, schema, path="$"):
    errors = []
    stype = schema.get("type")
    if stype == "object":
        if not isinstance(instance, dict):
            return [f"{path}: expected object"]
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}.{key}: missing required property")
        if not schema.get("additionalProperties", True):
            for key in instance:
                if key not in props:
                    errors.append(f"{path}.{key}: additional property not allowed")
        for key, sub in props.items():
            if key in instance:
                errors += validate(instance[key], sub, f"{path}.{key}")
    elif stype == "array":
        if not isinstance(instance, list):
            return [f"{path}: expected array"]
        for i, item in enumerate(instance):
            errors += validate(item, schema.get("items", {}), f"{path}[{i}]")
    elif stype == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            errors.append(f"{path}: expected integer")
    elif stype == "number":
        if not isinstance(instance, (int, float)) or isinstance(instance, bool):
            errors.append(f"{path}: expected number")
    elif stype == "boolean":
        if not isinstance(instance, bool):
            errors.append(f"{path}: expected boolean")
    elif stype == "string":
        if not isinstance(instance, str):
            errors.append(f"{path}: expected string")
        elif schema.get("format") == "uuid" and not GUID_RE.match(instance):
            errors.append(f"{path}: expected GUID format")
        elif schema.get("format") == "date-time" and not DATETIME_RE.match(instance):
            errors.append(f"{path}: expected date-time format")
    elif stype == ["string", "null"]:
        if instance is not None and not isinstance(instance, str):
            errors.append(f"{path}: expected string or null")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-dotnet", action="store_true",
                        help="skip regenerating goldens with the .NET generator")
    args = parser.parse_args()
    failures = []

    goldens = {p.name.replace(".golden.json", "") for p in EVENTS_DIR.glob("*.golden.json")}
    missing = EXPECTED_EVENTS - goldens
    extra = goldens - EXPECTED_EVENTS
    if missing:
        failures.append(f"missing golden events: {sorted(missing)}")
    if extra:
        failures.append(f"unexpected golden events: {sorted(extra)}")

    if not args.skip_dotnet:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp:
            subprocess.run(
                ["docker", "run", "--rm", "-v", f"{REPO_ROOT}:/repo", "-w", "/repo/src",
                 "mcr.microsoft.com/dotnet/core/sdk:3.1",
                 "dotnet", "run", "--project", "Tests/Contracts/EventContractsGenerator",
                 "-c", "Release", "--", f"/repo/{Path(tmp).name}"],
                check=True)
            for name in sorted(EXPECTED_EVENTS):
                fresh = Path(tmp) / f"{name}.golden.json"
                committed = EVENTS_DIR / f"{name}.golden.json"
                if not fresh.exists():
                    failures.append(f"{name}: generator produced no output")
                elif not filecmp.cmp(fresh, committed, shallow=False):
                    failures.append(
                        f"{name}: regenerated golden differs from committed\n"
                        f"  committed: {committed.read_text()}\n"
                        f"  fresh:     {fresh.read_text()}")

    for name in sorted(EXPECTED_EVENTS & goldens):
        golden = json.loads((EVENTS_DIR / f"{name}.golden.json").read_text())
        schema_path = EVENTS_DIR / f"{name}.schema.json"
        if not schema_path.exists():
            failures.append(f"{name}: missing JSON Schema snapshot")
            continue
        schema = json.loads(schema_path.read_text())
        failures += [f"{name}: {e}" for e in validate(golden, schema)]
        for base_field in ("Id", "CreationDate"):
            if base_field not in golden:
                failures.append(f"{name}: golden missing base field {base_field}")
            if base_field not in schema.get("required", []):
                failures.append(f"{name}: schema does not require base field {base_field}")
        desc = schema.get("description", "")
        if f"RabbitMQ routing key: {name}" not in desc or "eshop_event_bus" not in desc:
            failures.append(f"{name}: schema missing frozen routing-key documentation")

    if failures:
        print("Integration-event contract check FAILED:")
        for failure in failures:
            print(f"  {failure}")
        sys.exit(1)
    print(f"Integration-event contract check passed ({len(EXPECTED_EVENTS)} events)")


if __name__ == "__main__":
    main()
