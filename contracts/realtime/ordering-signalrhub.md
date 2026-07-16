# Ordering.SignalrHub — frozen realtime contract

Captured from the .NET Core 3.1 baseline (`src/Services/Ordering/Ordering.SignalrHub`)
before any protocol change. This slice replaces the SignalR protocol with
Socket.IO (an explicitly gated frontend+backend change; **no SignalR wire
compatibility is claimed**), preserving every user-visible semantic below.

## Baseline (.NET SignalR) contract

| Item | Value |
| --- | --- |
| Endpoint | `/hub/notificationhub` (websocket upgrade routed by the Envoy gateways at the same prefix) |
| JWT authority | `identityUrl` (`http://identity-api`), OIDC discovery |
| JWT audience | `orders.signalrhub` |
| Browser auth | `access_token` in the hub connection query string |
| Grouping | connection joins a group keyed by `Context.User.Identity.Name` (the `unique_name` token claim issued by the IdP ProfileService) |
| Message | `UpdatedOrderState` with anonymous body `{ OrderId, Status }` — the SignalR JSON protocol camelCases it on the wire, so the browser receives `{"orderId": <int>, "status": "<string>"}` (see `UpdatedOrderState.golden.json`) |
| Backplane | Redis (`AddStackExchangeRedis`) when `IsClusterEnv=True`, via `SignalrStoreConnectionString` |
| Consumed events | the six `OrderStatusChangedTo{Submitted,AwaitingValidation,StockConfirmed,Paid,Shipped,Cancelled}IntegrationEvent` (goldens in `contracts/events/`), RabbitMQ direct exchange `eshop_event_bus`, routing key = event class name, queue `Ordering.signalrhub` |
| Health | `/hc` + `/liveness` goldens in `contracts/health/ordering-signalrhub.*` (checks: `self`, `signalr-rabbitmqbus-check`) |
| Compose | service `ordering-signalrhub`, host port 5112 -> container 80; env vars `EventBusConnection`, `EventBusUserName`, `EventBusPassword`, `AzureServiceBusEnabled`, `identityUrl` (defaults from appsettings.json: `SubscriptionClientName=Ordering.signalrhub`, `EventBusRetryCount=5`) |

## Replacement (Python Socket.IO) mapping

`src/python/ordering_signalrhub`, python-socketio >= 5.11 (`AsyncRedisManager`
backplane when `IsClusterEnv=True`).

Preserved unchanged: URL path (as the Socket.IO engine path), audience,
`access_token` query-string auth, per-user grouping (Socket.IO room =
`unique_name`), the `UpdatedOrderState` event name and camelCase
`{orderId, status}` payload, all six consumed events (byte-exact golden
parity), queue name, exchange, routing keys, health-check names/shape,
Compose service name/ports/env vars.

Changed (gated with the frontend in the same slice): the wire protocol is
Socket.IO, so the Angular `SignalrService` now uses `socket.io-client` with
`path: '/hub/notificationhub'`. Deploy hub and SPA together; roll back
together.

Proof: `src/python/ordering_signalrhub/tests/` (unit golden-parity tests +
mixed-stack tests on real RabbitMQ publishing the exact .NET golden bytes to a
real Socket.IO browser client, including per-user isolation and rejected
unauthenticated/wrong-audience connections);
`src/Web/WebSPA/Client/modules/shared/services/signalr.service.spec.ts`
(client-side message semantics); `src/Web/WebSPA/e2e/order-status-realtime.spec.ts`
(full checkout -> realtime status toast journey against the compose stack).
