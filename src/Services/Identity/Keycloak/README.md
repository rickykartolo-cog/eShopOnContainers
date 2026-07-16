# External OIDC Identity Provider — Keycloak 26.x (configuration as code)

This directory stands up Keycloak 26.x as the future external OIDC IdP for
eShopOnContainers (master modernization prompt §4.5, sequencing step 1).

**IdentityServer4 is not removed or changed by this slice.** `identity-api`
keeps issuing tokens for every existing client; browser login is unaffected.
Keycloak runs side by side until clients/services are cut over in later
slices.

## Layout

| Path | Purpose |
| --- | --- |
| `realm/eshop-realm.json` | Realm import file (generated, committed) |
| `realm/generate_realm.py` | Deterministic generator for the realm file |
| `../../..//docker-compose.keycloak.yml` | Additive Compose overlay (`src/docker-compose.keycloak.yml`) |
| `.env.sample` | Required env vars (secrets stay out of source control) |
| `migration/` | Staged ASP.NET Identity → Keycloak user migration tooling |
| `tests/` | Offline realm/hash tests + live token/migration tests |

## Run Keycloak locally

```bash
cd src
cp Services/Identity/Keycloak/.env.sample .env   # then edit: set real secrets
docker compose -f docker-compose.keycloak.yml up -d
# realm import happens at startup; admin console: http://localhost:5106
```

Port `5106` is unused by every existing service, and no existing Compose
service, port, or environment variable is modified.

`eshop-realm.json` contains `${ENV_VAR}` placeholders (redirect URIs and
client secrets) that Keycloak resolves from container environment variables
at import time; defaults matching `docker-compose.override.yml` localhost
ports are supplied in the overlay.

## What is modeled (IdentityServer4 `Config.cs` parity)

- **API resources → audience client scopes**: `orders`, `basket`,
  `marketing`, `locations`, `mobileshoppingagg`, `webshoppingagg`,
  `orders.signalrhub`, `webhooks` — each scope adds itself as a token
  audience, matching current `AddJwtBearer` audience checks. A future-use
  `catalog` scope exists but is attached to **no** client, so
  currently-anonymous Catalog routes gain no authentication.
- **Clients**: `js`, `xamarin`, `mvc`, `mvctest`, `webhooksclient` and the
  seven `*swaggerui` clients (with `/swagger/oauth2-redirect.html` redirect
  URIs), preserving scopes, redirect/post-logout URIs, CORS origins, token
  lifetimes (1 h default, 2 h for `mvc`/`mvctest`/`webhooksclient`) and
  offline access.
- **Protocol modernization (the one permitted)**: the SPA client `js` uses
  Authorization Code + PKCE instead of implicit. IS4 "hybrid" clients map to
  Authorization Code (+ PKCE where IS4 required it, i.e. `xamarin`). Swagger
  clients keep implicit enabled (their current flow) and additionally allow
  code + PKCE for their own later cutover.
- **User claims**: the `eshop-profile` client scope reproduces every claim
  issued by `ProfileService.GetClaimsFromUser` (`name`, `last_name`,
  `card_*`, `address_*`, `preferred_username`, `unique_name`, `email`, ...).

## Staged user migration (no plaintext passwords, ever)

ASP.NET Core Identity v3 hashes are PBKDF2 (HMAC-SHA256, 10 000 iterations,
16-byte salt, 32-byte subkey) — natively supported by Keycloak's
`pbkdf2-sha256` credential algorithm, so hashes import as-is. Legacy v2
hashes (PBKDF2-HMAC-SHA1, 1 000 iterations) map to `pbkdf2`. Unparseable
hashes are imported without a credential plus an `UPDATE_PASSWORD` required
action (secure forced reset).

```bash
cd src/Services/Identity/Keycloak/migration
pip install -r requirements.txt

# 1. Export + validate (counts per hash version, forced-reset list)
export IDENTITY_DB_CONNECTION_STRING='Server=tcp:127.0.0.1,5433;Database=Microsoft.eShopOnContainers.Services.IdentityDb;User Id=sa;Password=...'
python3 export_users.py --out users-export.json

# 2. Dry run (no writes; prints reconciliation counts and planned actions)
export KEYCLOAK_URL=http://localhost:5106 KEYCLOAK_ADMIN_PASSWORD=...
python3 import_users.py --export-file users-export.json --dry-run

# 3. Import (idempotent upsert; never overwrites live Keycloak credentials)
python3 import_users.py --export-file users-export.json

# 4. Reconcile (source vs target counts + per-user claim/attribute diff)
python3 reconcile.py --export-file users-export.json

# 5. Delete the export file — it contains password hashes and PII
shred -u users-export.json
```

The original `AspNetUsers.Id` GUID is preserved as the Keycloak user id, so
the `sub` claim is identical before and after migration. All migrated users
are tagged `migrated_from=aspnet-identity`.

### Rollback

```bash
python3 rollback.py --dry-run    # list what would be removed
python3 rollback.py --yes        # delete all migrated users from Keycloak
# or remove the IdP entirely:
docker compose -f docker-compose.keycloak.yml down -v
```

The source Identity database is never modified, so IdentityServer4 login
keeps working during and after any rollback. Cutover of token consumers is a
later slice; until then rollback is simply "keep using identity-api".

## Tests

```bash
pip install -r Services/Identity/Keycloak/tests/requirements-test.txt
# offline (hash conversion, realm reproducibility/inventory):
python3 -m pytest Services/Identity/Keycloak/tests -v
# live (token issuance per audience, migrated-hash login, old-vs-new claims):
docker compose -f docker-compose.keycloak.yml up -d
KEYCLOAK_ADMIN_PASSWORD=... ESHOP_KEYCLOAK_MVCTEST_CLIENT_SECRET=... \
    python3 -m pytest Services/Identity/Keycloak/tests -v
```

Live tests self-skip when Keycloak is unreachable, so CI without Docker
still runs the offline suite.

## Known limitations / risks

- `security_stamp` claim checks (IS4 `ProfileService.IsActiveAsync`) have no
  Keycloak equivalent; Keycloak session/offline-token revocation replaces
  them at cutover time.
- `mvctest` has Direct Access Grants enabled solely so automated tests can
  obtain tokens; it mirrors IS4's test-only client. Disable it in
  production realms.
- Keycloak issues additional standard claims (`azp`, `typ`, `sid`, ...) on
  top of the IS4-equivalent set; consumers validate issuer/audience and
  ignore extras.
- Swagger UI clients keep implicit flow enabled to match current behavior;
  move them to code + PKCE when each service's Swagger UI is cut over.
