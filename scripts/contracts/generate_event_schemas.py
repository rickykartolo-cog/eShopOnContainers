#!/usr/bin/env python3
"""Generate JSON Schema (draft-07) snapshots from the golden integration-event JSON.

Types are inferred from the golden examples produced by the .NET Newtonsoft
serializer. GUID and ISO-8601 date-time strings get `format` annotations.
All observed properties are required and additional properties are rejected,
freezing property names, casing, and types.

Usage: generate_event_schemas.py <events_dir>
"""
import json
import re
import sys
from pathlib import Path

GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def schema_for(value):
    if value is None:
        return {"type": ["string", "null"]}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        if GUID_RE.match(value):
            return {"type": "string", "format": "uuid"}
        if DATETIME_RE.match(value):
            return {"type": "string", "format": "date-time"}
        return {"type": "string"}
    if isinstance(value, list):
        items = schema_for(value[0]) if value else {}
        return {"type": "array", "items": items}
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {k: schema_for(v) for k, v in value.items()},
            "required": list(value.keys()),
            "additionalProperties": False,
        }
    raise TypeError(f"unsupported value: {value!r}")


def main():
    events_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "contracts/events")
    for golden in sorted(events_dir.glob("*.golden.json")):
        event_name = golden.name.replace(".golden.json", "")
        doc = json.loads(golden.read_text())
        schema = schema_for(doc)
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": event_name,
            "description": (
                f"Frozen contract for {event_name}. RabbitMQ routing key: {event_name} "
                f"(exchange eshop_event_bus); Azure Service Bus label: "
                f"{event_name[: -len('IntegrationEvent')]}."
            ),
            **schema,
        }
        out = events_dir / f"{event_name}.schema.json"
        out.write_text(json.dumps(schema, indent=2) + "\n")
        print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
