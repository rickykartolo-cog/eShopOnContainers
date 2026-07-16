#!/usr/bin/env python3
"""Staged import of exported ASP.NET Identity users into Keycloak.

Stages:
  1. ``export_users.py``  — export + hash validation (see that script).
  2. ``import_users.py --dry-run``  — full transform pass, no writes;
     prints reconciliation counts and every planned action.
  3. ``import_users.py``  — idempotent upsert. Users whose hash cannot be
     imported are created without a credential and with the
     UPDATE_PASSWORD required action (secure forced reset). No plaintext
     passwords are ever read or written.
  4. ``reconcile.py``  — compare source export vs Keycloak state.
  5. ``rollback.py``  — remove every user this tool created.

All imported users are tagged with attribute ``migrated_from=aspnet-identity``
so reconciliation and rollback only ever touch migrated users.
"""
import argparse
import json
import sys
import uuid

from aspnet_hash import UnsupportedHashError, to_keycloak_credential
from keycloak_admin import KeycloakAdmin

MIGRATION_ATTRIBUTE = "migrated_from"
MIGRATION_SOURCE = "aspnet-identity"

# ApplicationUser column -> Keycloak user attribute (ProfileService claim names).
ATTRIBUTE_MAP = {
    "Name": "name",
    "LastName": "last_name",
    "CardNumber": "card_number",
    "CardHolderName": "card_holder",
    "SecurityNumber": "card_security_number",
    "Expiration": "card_expiration",
    "City": "address_city",
    "Country": "address_country",
    "State": "address_state",
    "Street": "address_street",
    "ZipCode": "address_zip_code",
    "PhoneNumber": "phone_number",
}


def to_keycloak_user(user):
    """Transform an exported AspNetUsers row into a Keycloak UserRepresentation."""
    attributes = {MIGRATION_ATTRIBUTE: [MIGRATION_SOURCE], "aspnet_user_id": [user["Id"]]}
    for column, attribute in ATTRIBUTE_MAP.items():
        value = user.get(column)
        if value not in (None, ""):
            attributes[attribute] = [str(value)]

    representation = {
        "username": user["UserName"],
        "email": user.get("Email"),
        "emailVerified": bool(user.get("EmailConfirmed")),
        "firstName": user.get("Name") or "",
        "lastName": user.get("LastName") or "",
        "enabled": True,
        "attributes": attributes,
        "requiredActions": [],
    }
    # Preserve the IdentityServer4 `sub` claim: AspNetUsers.Id is a GUID and
    # Keycloak accepts a caller-supplied UUID id at creation time.
    try:
        representation["id"] = str(uuid.UUID(user["Id"]))
    except (ValueError, KeyError, TypeError):
        pass

    forced_reset_reason = None
    try:
        representation["credentials"] = [to_keycloak_credential(user.get("PasswordHash") or "")]
    except UnsupportedHashError as exc:
        forced_reset_reason = str(exc)
        representation["requiredActions"] = ["UPDATE_PASSWORD"]
    return representation, forced_reset_reason


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-file", default="users-export.json")
    parser.add_argument("--dry-run", action="store_true", help="transform and report only; write nothing")
    args = parser.parse_args()

    with open(args.export_file, encoding="utf-8") as f:
        export = json.load(f)
    users = export["users"]

    admin = None if args.dry_run else KeycloakAdmin()

    counts = {"total": len(users), "created": 0, "updated": 0, "skipped": 0, "forced_reset": 0, "errors": 0}
    for user in users:
        username = user.get("UserName")
        if not username:
            counts["skipped"] += 1
            print(f"SKIP: user {user.get('Id')} has no UserName")
            continue
        representation, forced_reset_reason = to_keycloak_user(user)
        if forced_reset_reason:
            counts["forced_reset"] += 1
            print(f"FORCED-RESET: {username}: {forced_reset_reason}")
        if args.dry_run:
            print(f"DRY-RUN: would upsert {username}")
            counts["created"] += 1
            continue
        try:
            existing = admin.find_user(username)
            if existing:
                update = dict(representation)
                update.pop("id", None)
                update.pop("credentials", None)  # never overwrite live credentials
                admin.update_user(existing["id"], update)
                counts["updated"] += 1
                print(f"UPDATED: {username}")
            else:
                # partialImport preserves the supplied id so the `sub` claim
                # matches the IdentityServer4-issued value.
                admin.partial_import_users([representation])
                counts["created"] += 1
                print(f"CREATED: {username}")
        except Exception as exc:  # keep going; reconcile.py surfaces gaps
            counts["errors"] += 1
            print(f"ERROR: {username}: {exc}", file=sys.stderr)

    print(json.dumps(counts, indent=2))
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
