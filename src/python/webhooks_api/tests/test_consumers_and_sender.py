"""Consumer/dispatch behavior against .NET-serialized golden bytes (mixed-stack
oracle at the wire-format level), callback payload/token/header parity, and the
duplicate-delivery contract (repeat POST per receipt, no state change — exactly
the .NET at-least-once behavior)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from webhooks_api.consumers import WebhooksEventConsumers
from webhooks_api.events import OrderStatusChangedToShippedIntegrationEvent
from webhooks_api.models import WebhookSubscription, WebhookType
from webhooks_api.sender import TOKEN_HEADER, WebhookData

GOLDEN_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"


async def _add_subscription(session_factory, hook_type: WebhookType, token: str | None = "tok") -> None:
    async with session_factory() as session:
        session.add(
            WebhookSubscription(
                Type=int(hook_type),
                Date=datetime.now(UTC),
                DestUrl="http://webhooks-client/hooks",
                Token=token,
                UserId="alice",
            )
        )
        await session.commit()


async def test_order_shipped_event_posts_webhook(session_factory, event_bus, sender, transport):
    await _add_subscription(session_factory, WebhookType.OrderShipped)
    consumers = WebhooksEventConsumers(session_factory, sender)
    await consumers.subscribe_all(event_bus)

    golden = (GOLDEN_DIR / "OrderStatusChangedToShippedIntegrationEvent.golden.json").read_bytes()
    await event_bus.deliver("OrderStatusChangedToShippedIntegrationEvent", golden)

    assert len(transport.hook_posts) == 1
    request = transport.hook_posts[0]
    assert request.headers[TOKEN_HEADER] == "tok"
    assert request.headers["content-type"] == "application/json; charset=utf-8"
    body = json.loads(request.content)
    assert list(body) == ["When", "Payload", "Type"]
    assert body["Type"] == "OrderShipped"
    payload = json.loads(body["Payload"])
    assert payload["OrderId"] == 42
    assert payload["OrderStatus"] == "shipped"
    assert payload["BuyerName"] == "alice@eshop"


async def test_order_paid_event_posts_webhook(session_factory, event_bus, sender, transport):
    await _add_subscription(session_factory, WebhookType.OrderPaid, token=None)
    consumers = WebhooksEventConsumers(session_factory, sender)
    await consumers.subscribe_all(event_bus)

    golden = (GOLDEN_DIR / "OrderStatusChangedToPaidIntegrationEvent.golden.json").read_bytes()
    await event_bus.deliver("OrderStatusChangedToPaidIntegrationEvent", golden)

    assert len(transport.hook_posts) == 1
    request = transport.hook_posts[0]
    assert TOKEN_HEADER not in request.headers  # blank token → no header, like .NET
    body = json.loads(request.content)
    assert body["Type"] == "OrderPaid"
    payload = json.loads(body["Payload"])
    assert set(payload) == {"OrderId", "OrderStockItems", "Id", "CreationDate"}


async def test_product_price_changed_is_noop(session_factory, event_bus, sender, transport):
    await _add_subscription(session_factory, WebhookType.CatalogItemPriceChange)
    consumers = WebhooksEventConsumers(session_factory, sender)
    await consumers.subscribe_all(event_bus)

    golden = (GOLDEN_DIR / "ProductPriceChangedIntegrationEvent.golden.json").read_bytes()
    await event_bus.deliver("ProductPriceChangedIntegrationEvent", golden)

    # The .NET handler body is empty: no webhook is sent even with a subscription.
    assert transport.hook_posts == []


async def test_events_without_subscribers_send_nothing(session_factory, event_bus, sender, transport):
    consumers = WebhooksEventConsumers(session_factory, sender)
    await consumers.subscribe_all(event_bus)
    golden = (GOLDEN_DIR / "OrderStatusChangedToShippedIntegrationEvent.golden.json").read_bytes()
    await event_bus.deliver("OrderStatusChangedToShippedIntegrationEvent", golden)
    assert transport.hook_posts == []


async def test_duplicate_delivery_matches_dotnet_contract(session_factory, event_bus, sender, transport):
    """At-least-once parity: a duplicate broker delivery repeats the POST (one
    per receipt, same as the .NET handler) and produces no state change."""
    await _add_subscription(session_factory, WebhookType.OrderShipped)
    consumers = WebhooksEventConsumers(session_factory, sender)
    await consumers.subscribe_all(event_bus)

    golden = (GOLDEN_DIR / "OrderStatusChangedToShippedIntegrationEvent.golden.json").read_bytes()
    await event_bus.deliver("OrderStatusChangedToShippedIntegrationEvent", golden)
    await event_bus.deliver("OrderStatusChangedToShippedIntegrationEvent", golden)

    assert len(transport.hook_posts) == 2
    bodies = [json.loads(request.content) for request in transport.hook_posts]
    assert bodies[0]["Payload"] == bodies[1]["Payload"]
    # No extra side effects: the subscription table is untouched.
    async with session_factory() as session:
        from sqlalchemy import func, select

        count = (await session.execute(select(func.count()).select_from(WebhookSubscription))).scalar_one()
    assert count == 1


async def test_failed_delivery_does_not_block_other_receivers(session_factory, event_bus, sender, transport):
    async with session_factory() as session:
        for dest in ("http://webhooks-client/fails", "http://webhooks-client/hooks"):
            session.add(
                WebhookSubscription(
                    Type=int(WebhookType.OrderShipped),
                    Date=datetime.now(UTC),
                    DestUrl=dest,
                    Token="tok",
                    UserId="alice",
                )
            )
        await session.commit()

    # Make POSTs to /fails raise a transport error.
    original_handler = transport.handler

    def handler(request):
        if request.method == "POST" and request.url.path.endswith("/fails"):
            import httpx

            raise httpx.ConnectError("refused", request=request)
        return original_handler(request)

    import httpx

    from webhooks_api.sender import WebhooksSender

    failing_sender = WebhooksSender(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    consumers = WebhooksEventConsumers(session_factory, failing_sender)
    await consumers.subscribe_all(event_bus)

    golden = (GOLDEN_DIR / "OrderStatusChangedToShippedIntegrationEvent.golden.json").read_bytes()
    await event_bus.deliver("OrderStatusChangedToShippedIntegrationEvent", golden)

    assert len(transport.hook_posts) == 1
    assert transport.hook_posts[0].url.path.endswith("/hooks")


def test_webhook_data_serialization_shape():
    event = OrderStatusChangedToShippedIntegrationEvent(OrderId=42, OrderStatus="shipped", BuyerName="alice@eshop")
    data = WebhookData(WebhookType.OrderShipped, event)
    body = json.loads(data.to_json())
    assert list(body) == ["When", "Payload", "Type"]
    assert body["Type"] == "OrderShipped"
    payload = json.loads(body["Payload"])
    assert list(payload) == ["OrderId", "OrderStatus", "BuyerName", "Id", "CreationDate"]
