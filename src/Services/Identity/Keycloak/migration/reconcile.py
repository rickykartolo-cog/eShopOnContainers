#!/usr/bin/env python3
"""Reconcile the ASP.NET Identity export against migrated Keycloak users.

Reports source/target counts, missing users, and per-user attribute
(claim) mismatches so a migration can be signed off with evidence.
Exit code is non-zero when reconciliation fails.
"""
import argparse
import json
import sys

from import_users import MIGRATION_ATTRIBUTE, MIGRATION_SOURCE, to_keycloak_user
from keycloak_admin import KeycloakAdmin


def fetch_migrated_users(admin):
    users, first = {}, 0
    while True:
        page = admin.list_users(first=first, max_results=100, query=f"{MIGRATION_ATTRIBUTE}:{MIGRATION_SOURCE}")
        if not page:
            return users
        for user in page:
            users[user["username"]] = user
        first += len(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-file", default="users-export.json")
    args = parser.parse_args()

    with open(args.export_file, encoding="utf-8") as f:
        source_users = json.load(f)["users"]

    admin = KeycloakAdmin()
    migrated = fetch_migrated_users(admin)

    report = {
        "source_count": len(source_users),
        "migrated_count": len(migrated),
        "missing_in_keycloak": [],
        "attribute_mismatches": [],
    }

    for user in source_users:
        username = user.get("UserName")
        if not username:
            continue
        target = migrated.get(username)
        if target is None:
            report["missing_in_keycloak"].append(username)
            continue
        expected, _ = to_keycloak_user(user)
        actual_attrs = target.get("attributes") or {}
        for attribute, values in expected["attributes"].items():
            if (actual_attrs.get(attribute) or [None])[0] != values[0]:
                report["attribute_mismatches"].append(
                    {"username": username, "attribute": attribute, "expected": values[0],
                     "actual": (actual_attrs.get(attribute) or [None])[0]}
                )
        if target.get("email") != expected.get("email"):
            report["attribute_mismatches"].append(
                {"username": username, "attribute": "email", "expected": expected.get("email"),
                 "actual": target.get("email")}
            )

    ok = not report["missing_in_keycloak"] and not report["attribute_mismatches"]
    report["result"] = "PASS" if ok else "FAIL"
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
