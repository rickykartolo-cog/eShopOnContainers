"""Frozen HTTP contract: routes, auth, idempotency, response shapes/casing
(oracle: Ordering.FunctionalTests + OrdersController)."""

from __future__ import annotations

import uuid

import pytest
from eshop_common.health.core import HealthCheckRegistry

from ordering_api.app import create_app
from ordering_api.consumers import OrderingEventConsumers
from tests.conftest import TEST_USER_ID, TEST_USER_NAME

CHECKOUT_BODY = {
    "UserId": TEST_USER_ID,
    "UserName": TEST_USER_NAME,
    "City": "Seattle",
    "Street": "123 Main St",
    "State": "WA",
    "Country": "U.S.",
    "ZipCode": "98101",
    "CardNumber": "4012888888881881",
    "CardHolderName": "Alice Smith",
    "CardExpiration": "2999-12-31T00:00:00Z",
    "CardSecurityNumber": "535",
    "CardTypeId": 1,
    "Buyer": TEST_USER_NAME,
    "Basket": {
        "BuyerId": TEST_USER_ID,
        "Items": [
            {
                "Id": "basket-item-1",
                "ProductId": 1,
                "ProductName": ".NET Bot Black Hoodie",
                "UnitPrice": 19.50,
                "OldUnitPrice": 18.00,
                "Quantity": 2,
                "PictureUrl": "http://pic/1",
            }
        ],
    },
}


async def create_order(session_factory, event_bus, mediator, request_id: uuid.UUID | None = None) -> int:
    """Drive checkout through the UserCheckoutAccepted consumer like the real flow."""
    from ordering_api.events import UserCheckoutAcceptedIntegrationEvent

    consumers = OrderingEventConsumers(session_factory, event_bus, mediator)
    event = UserCheckoutAcceptedIntegrationEvent.model_validate(
        {**CHECKOUT_BODY, "RequestId": str(request_id or uuid.uuid4())}
    )
    await consumers.on_user_checkout_accepted(event)
    submitted = [e for e in event_bus.published if type(e).__name__ == "OrderStatusChangedToSubmittedIntegrationEvent"]
    assert submitted, "checkout did not create an order"
    return submitted[-1].order_id


@pytest.mark.anyio
async def test_unauthenticated_requests_are_rejected(ordering_settings, session_factory, event_bus, mediator):
    app = create_app(ordering_settings, session_factory, HealthCheckRegistry(), mediator, event_bus=event_bus)
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/orders")
        assert response.status_code == 401


async def test_get_card_types_matches_frozen_shape(client):
    response = await client.get("/api/v1/orders/cardtypes")
    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "name": "Amex"},
        {"id": 2, "name": "Visa"},
        {"id": 3, "name": "MasterCard"},
    ]


async def test_routing_is_case_insensitive(client):
    response = await client.get("/api/v1/Orders/CardTypes")
    assert response.status_code == 200


async def test_get_missing_order_returns_404(client):
    response = await client.get("/api/v1/orders/999999")
    assert response.status_code == 404


async def test_get_orders_empty_for_new_buyer(client):
    response = await client.get("/api/v1/orders")
    assert response.status_code == 200
    assert response.json() == []


async def test_checkout_then_get_order_and_list(client, session_factory, event_bus, mediator):
    order_id = await create_order(session_factory, event_bus, mediator)

    response = await client.get(f"/api/v1/orders/{order_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["ordernumber"] == order_id
    assert body["status"] == "submitted"
    assert body["city"] == "Seattle"
    assert body["street"] == "123 Main St"
    assert body["zipcode"] == "98101"
    assert body["country"] == "U.S."
    assert body["total"] == 39.0
    assert body["orderitems"] == [
        {
            "productname": ".NET Bot Black Hoodie",
            "units": 2,
            "unitprice": 19.5,
            "pictureurl": "http://pic/1",
        }
    ]

    listing = await client.get("/api/v1/orders")
    assert listing.status_code == 200
    rows = listing.json()
    assert [row["ordernumber"] for row in rows] == [order_id]
    assert rows[0]["status"] == "submitted"
    assert rows[0]["total"] == 39.0


async def test_cancel_requires_request_id(client):
    response = await client.put("/api/v1/orders/cancel", json={"orderNumber": 1})
    assert response.status_code == 400
    response = await client.put(
        "/api/v1/orders/cancel",
        json={"orderNumber": 1},
        headers={"x-requestid": str(uuid.UUID(int=0))},
    )
    assert response.status_code == 400


async def test_cancel_unknown_order_returns_400(client):
    response = await client.put(
        "/api/v1/orders/cancel",
        json={"orderNumber": 424242},
        headers={"x-requestid": str(uuid.uuid4())},
    )
    assert response.status_code == 400


async def test_cancel_order_and_duplicate_request_is_idempotent(
    client, session_factory, event_bus, mediator
):
    order_id = await create_order(session_factory, event_bus, mediator)
    request_id = str(uuid.uuid4())

    response = await client.put(
        "/api/v1/orders/cancel", json={"orderNumber": order_id}, headers={"x-requestid": request_id}
    )
    assert response.status_code == 200

    order = await client.get(f"/api/v1/orders/{order_id}")
    assert order.json()["status"] == "cancelled"

    duplicate = await client.put(
        "/api/v1/orders/cancel", json={"orderNumber": order_id}, headers={"x-requestid": request_id}
    )
    assert duplicate.status_code == 200  # duplicate request short-circuits to success


async def test_ship_requires_paid_status(client, session_factory, event_bus, mediator):
    order_id = await create_order(session_factory, event_bus, mediator)
    response = await client.put(
        "/api/v1/orders/ship", json={"orderNumber": order_id}, headers={"x-requestid": str(uuid.uuid4())}
    )
    assert response.status_code == 400  # submitted -> shipped is an invalid transition


async def test_create_order_draft_shape(client):
    response = await client.post(
        "/api/v1/orders/draft",
        json={
            "buyerId": TEST_USER_ID,
            "items": [
                {
                    "id": "basket-item-1",
                    "productId": 1,
                    "productName": ".NET Bot Black Hoodie",
                    "unitPrice": 19.5,
                    "oldUnitPrice": 18.0,
                    "quantity": 2,
                    "pictureUrl": "http://pic/1",
                },
                {
                    "id": "basket-item-2",
                    "productId": 1,
                    "productName": ".NET Bot Black Hoodie",
                    "unitPrice": 19.5,
                    "oldUnitPrice": 18.0,
                    "quantity": 1,
                    "pictureUrl": "http://pic/1",
                },
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 58.5
    # duplicate products merge into a single order item (aggregate invariant)
    assert len(body["orderItems"]) == 1
    item = body["orderItems"][0]
    assert item["productId"] == 1
    assert item["units"] == 3
    assert item["unitPrice"] == 19.5
    assert item["discount"] == 0.0
