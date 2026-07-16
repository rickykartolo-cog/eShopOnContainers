#!/usr/bin/env python3
"""OpenAPI contract gate.

Fetches /swagger/v1/swagger.json from a running candidate service, compares it
against the frozen golden document, and runs semantic assertions. Any drift in
routes, methods, parameters, schemas, required fields, casing, security, status
codes, or content types fails the gate.

Usage: check_openapi.py <service> <base_url> [--report <path>]
Example: check_openapi.py catalog http://localhost:5101
"""
import argparse
import difflib
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def semantic_errors(golden, candidate):
    errors = []

    def check(path, g, c):
        if isinstance(g, dict):
            if not isinstance(c, dict):
                errors.append(f"{path}: expected object, got {type(c).__name__}")
                return
            for key in g:
                if key not in c:
                    errors.append(f"{path}.{key}: missing in candidate")
                else:
                    check(f"{path}.{key}", g[key], c[key])
            for key in c:
                if key not in g:
                    errors.append(f"{path}.{key}: unexpected addition in candidate")
        elif isinstance(g, list):
            if g != c:
                errors.append(f"{path}: list differs (golden={g!r}, candidate={c!r})")
        elif g != c:
            errors.append(f"{path}: value differs (golden={g!r}, candidate={c!r})")

    for section in ("paths", "components", "security", "tags", "info", "openapi"):
        if section in golden or (isinstance(candidate, dict) and section in candidate):
            check(section, golden.get(section), candidate.get(section))
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("service")
    parser.add_argument("base_url")
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    golden_path = REPO_ROOT / "contracts" / "openapi" / f"{args.service}.swagger.json"
    golden = json.loads(golden_path.read_text())
    candidate = fetch(f"{args.base_url.rstrip('/')}/swagger/v1/swagger.json")

    golden_pretty = json.dumps(golden, indent=2, ensure_ascii=False, sort_keys=True)
    candidate_pretty = json.dumps(candidate, indent=2, ensure_ascii=False, sort_keys=True)

    diff = list(difflib.unified_diff(
        golden_pretty.splitlines(), candidate_pretty.splitlines(),
        fromfile=f"golden/{args.service}.swagger.json",
        tofile=f"candidate/{args.service}.swagger.json", lineterm=""))
    errors = semantic_errors(golden, candidate)

    if args.report:
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# OpenAPI contract report: {args.service}", ""]
        lines.append("PASS" if not errors and not diff else "FAIL")
        if errors:
            lines += ["", "## Semantic violations", *errors]
        if diff:
            lines += ["", "## Unified diff", *diff]
        report.write_text("\n".join(lines) + "\n")

    if errors or diff:
        print(f"OpenAPI contract check FAILED for {args.service}:")
        for err in errors[:50]:
            print(f"  {err}")
        if diff:
            print("\n".join(diff[:200]))
        sys.exit(1)
    print(f"OpenAPI contract check passed for {args.service}")


if __name__ == "__main__":
    main()
