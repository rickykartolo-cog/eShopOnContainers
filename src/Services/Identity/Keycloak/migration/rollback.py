#!/usr/bin/env python3
"""Roll back a user migration: delete every Keycloak user tagged
``migrated_from=aspnet-identity``.

Only migrated users are ever touched; the source ASP.NET Identity database
is never modified by any script in this tooling, so IdentityServer4 login
keeps working throughout (and after) a rollback.
"""
import argparse
import sys

from import_users import MIGRATION_ATTRIBUTE, MIGRATION_SOURCE
from keycloak_admin import KeycloakAdmin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="list users that would be deleted")
    parser.add_argument("--yes", action="store_true", help="required to actually delete")
    args = parser.parse_args()

    admin = KeycloakAdmin()
    query = f"{MIGRATION_ATTRIBUTE}:{MIGRATION_SOURCE}"

    deleted = 0
    while True:
        page = admin.list_users(first=0, max_results=100, query=query)
        if not page:
            break
        for user in page:
            if args.dry_run or not args.yes:
                print(f"WOULD DELETE: {user['username']} ({user['id']})")
            else:
                admin.delete_user(user["id"])
                print(f"DELETED: {user['username']} ({user['id']})")
                deleted += 1
        if args.dry_run or not args.yes:
            break

    if not args.dry_run and not args.yes:
        print("Refusing to delete without --yes")
        return 2
    print(f"Deleted {deleted} migrated users")
    return 0


if __name__ == "__main__":
    sys.exit(main())
