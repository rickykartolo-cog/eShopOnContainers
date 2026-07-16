#!/usr/bin/env python3
"""Export ASP.NET Identity users from the eShop IdentityDb to a JSON file.

Reads the AspNetUsers table (password hashes stay hashed; no plaintext is
ever handled) and validates every hash for Keycloak import compatibility.

Usage:
    IDENTITY_DB_CONNECTION_STRING='Server=tcp:127.0.0.1,5433;Database=Microsoft.eShopOnContainers.Services.IdentityDb;User Id=sa;Password=...' \
        python3 export_users.py --out users-export.json
"""
import argparse
import json
import os
import sys

from aspnet_hash import UnsupportedHashError, parse_aspnet_password_hash

COLUMNS = [
    "Id",
    "UserName",
    "NormalizedUserName",
    "Email",
    "NormalizedEmail",
    "EmailConfirmed",
    "PasswordHash",
    "SecurityStamp",
    "PhoneNumber",
    "PhoneNumberConfirmed",
    "TwoFactorEnabled",
    "LockoutEnd",
    "LockoutEnabled",
    "AccessFailedCount",
    "CardNumber",
    "SecurityNumber",
    "Expiration",
    "CardHolderName",
    "CardType",
    "Street",
    "City",
    "State",
    "Country",
    "ZipCode",
    "Name",
    "LastName",
]


def export_users(connection_string):
    import pyodbc  # local import: only needed for export against SQL Server

    conn_str = connection_string
    if "driver=" not in conn_str.lower():
        conn_str = "Driver={ODBC Driver 18 for SQL Server};TrustServerCertificate=yes;" + conn_str
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {', '.join(COLUMNS)} FROM dbo.AspNetUsers")
    rows = cursor.fetchall()
    users = []
    for row in rows:
        user = {}
        for col, value in zip(COLUMNS, row):
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            user[col] = value
        users.append(user)
    conn.close()
    return users


def validate(users):
    summary = {
        "total": len(users),
        "importable_hashes": 0,
        "forced_reset": 0,
        "missing_username": 0,
        "hash_versions": {},
        "forced_reset_users": [],
    }
    for user in users:
        if not user.get("UserName"):
            summary["missing_username"] += 1
        try:
            parsed = parse_aspnet_password_hash(user.get("PasswordHash") or "")
            summary["importable_hashes"] += 1
            key = f"v{parsed['version']}-{parsed['algorithm']}"
            summary["hash_versions"][key] = summary["hash_versions"].get(key, 0) + 1
        except UnsupportedHashError as exc:
            summary["forced_reset"] += 1
            summary["forced_reset_users"].append({"UserName": user.get("UserName"), "reason": str(exc)})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="users-export.json")
    args = parser.parse_args()

    connection_string = os.environ.get("IDENTITY_DB_CONNECTION_STRING")
    if not connection_string:
        print("ERROR: IDENTITY_DB_CONNECTION_STRING is not set", file=sys.stderr)
        return 2

    users = export_users(connection_string)
    summary = validate(users)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "users": users}, f, indent=2, default=str)

    print(json.dumps(summary, indent=2))
    print(f"Exported {summary['total']} users to {args.out}")
    print("NOTE: the export contains password hashes and PII. Store it securely and delete it after migration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
