#!/usr/bin/env python3
"""Normalize an ASP.NET HealthChecks UI response (/hc) for golden comparison.

The JSON shape emitted by UIResponseWriter.WriteHealthCheckUIResponse is frozen;
only the duration values are nondeterministic. Replaces every duration with a
placeholder while preserving key order, so byte-level diffs are meaningful.

Usage: normalize_hc.py < raw.json > normalized.json
"""
import json
import sys
from collections import OrderedDict


def normalize(doc):
    if isinstance(doc, dict):
        out = OrderedDict()
        for key, value in doc.items():
            if key in ("totalDuration", "duration"):
                out[key] = "<duration>"
            else:
                out[key] = normalize(value)
        return out
    if isinstance(doc, list):
        return [normalize(item) for item in doc]
    return doc


def main():
    doc = json.load(sys.stdin, object_pairs_hook=OrderedDict)
    json.dump(normalize(doc), sys.stdout, separators=(",", ":"))


if __name__ == "__main__":
    main()
