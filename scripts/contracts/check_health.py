#!/usr/bin/env python3
"""Health-check contract gate.

Fetches /hc and /liveness from a running candidate, normalizes nondeterministic
durations, and compares against the golden responses captured from the .NET
reference (exact UIResponseWriter.WriteHealthCheckUIResponse shape).

Usage: check_health.py <service> <base_url>
"""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NORMALIZER = REPO_ROOT / "scripts" / "contracts" / "normalize_hc.py"


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8"), resp.headers.get("Content-Type", "")


def main():
    service, base_url = sys.argv[1], sys.argv[2].rstrip("/")
    failures = []

    hc_raw, hc_ct = fetch(f"{base_url}/hc")
    normalized = subprocess.run(
        [sys.executable, str(NORMALIZER)], input=hc_raw, capture_output=True,
        text=True, check=True).stdout
    golden = (REPO_ROOT / "contracts" / "health" / f"{service}.hc.golden.json").read_text()
    if json.loads(normalized) != json.loads(golden):
        failures.append(f"/hc body drift:\n  golden:    {golden}\n  candidate: {normalized}")
    if "application/json" not in hc_ct:
        failures.append(f"/hc content-type drift: {hc_ct}")

    liveness_raw, _ = fetch(f"{base_url}/liveness")
    golden_liveness = (REPO_ROOT / "contracts" / "health" / f"{service}.liveness.golden.txt").read_text()
    if liveness_raw != golden_liveness:
        failures.append(f"/liveness drift: golden={golden_liveness!r} candidate={liveness_raw!r}")

    if failures:
        print(f"Health contract check FAILED for {service}:")
        for failure in failures:
            print(f"  {failure}")
        sys.exit(1)
    print(f"Health contract check passed for {service}")


if __name__ == "__main__":
    main()
