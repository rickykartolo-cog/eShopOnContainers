# Frozen authentication contracts (.NET reference baseline)

Captured from the .NET Core 3.1 baseline at `origin/main`
(`31ab9b62b9fb02fb1c1eb7cadef285c5e6ca6731`). Any Python replacement must
validate JWT bearer tokens with the same authority and exact audience, and must
not add authentication to routes that are anonymous today.

## JWT bearer configuration per service

| Service | Authority (env var) | Audience | Notes |
| --- | --- | --- | --- |
| Basket.API | `identityUrl` (`http://identity-api`) | `basket` | All `api/v1/basket` routes require auth (`[Authorize]` at controller). Checkout requires `x-requestid` header. |
| Catalog.API | n/a | n/a | **Not JWT-protected.** No `catalog` API resource exists in IdentityServer config. Do not add auth during contract-preserving cutover. |
| Identity.API | n/a (it is the IdP, IdentityServer4) | n/a | Issues tokens for clients/scopes listed below. |
| Locations.API | `identityUrl` (`http://identity-api`) | `locations` | `api/v1/locations` routes require auth. |
| Marketing.API | `identityUrl` (`http://identity-api`) | `marketing` | `api/v1/campaigns` routes require auth. |
| Ordering.API | `identityUrl` (`http://identity-api`) | `orders` | `api/v1/orders` routes require auth; cancel/ship require `x-requestid`. |
| Ordering.SignalrHub | `identityUrl` (`http://identity-api`) | `orders.signalrhub` | Hub endpoint `/hub/notificationhub`; browser auth supports `access_token` query string; groups keyed by authenticated user name. |
| Payment.API | n/a | n/a | No HTTP API surface (event-driven only) besides health endpoints. |
| Webhooks.API | `IdentityUrl` (`http://identity-api`) — note casing | `webhooks` | `api/v1/webhooks` routes require auth. |

Aggregator audiences (BFFs, unchanged this slice): `mobileshoppingagg`, `webshoppingagg`.

`RequireHttpsMetadata = false` in the containerized development topology; token
validation uses the OIDC discovery document from the authority above.

## IdentityServer4 clients/scopes to be preserved by the external IdP

- SPA client `js`: implicit flow, scopes `openid profile orders basket marketing locations webshoppingagg orders.signalrhub webhooks`.
- Xamarin client `xamarin`: hybrid flow + PKCE + offline access.
- MVC clients `mvc`, `mvctest`: hybrid flow, `/signin-oidc`, `/signout-callback-oidc`.
- `webhooksclient`: hybrid flow with webhooks scope.
- Swagger UI clients: `locationsswaggerui`, `marketingswaggerui`, `basketswaggerui`, `orderingswaggerui`, `mobileshoppingaggswaggerui`, `webshoppingaggswaggerui`, `webhooksswaggerui` (redirect `/swagger/oauth2-redirect.html`).

Source of truth: `src/Services/Identity/Identity.API/Configuration/Config.cs`.

## Health endpoints (all services)

- `/liveness`: self-only check; plain-text body `Healthy`, HTTP 200.
- `/hc`: dependency checks; exact `UIResponseWriter.WriteHealthCheckUIResponse`
  JSON shape frozen under `contracts/health/*.hc.golden.json` (durations
  normalized to `<duration>`); content type `application/json`.

## Status-code and header behavior

Frozen per-route status codes, parameters, content types and response schemas
are captured in the OpenAPI documents under `contracts/openapi/`. Idempotency
headers: `x-requestid` (GUID) on Basket checkout and Ordering cancel/ship.
