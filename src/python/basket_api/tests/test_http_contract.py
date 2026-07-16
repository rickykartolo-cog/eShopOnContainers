"""HTTP contract parity with BasketController, using Basket.FunctionalTests
scenarios as oracles (get/update/checkout with and without x-requestid)."""

import json
import uuid

from conftest import TEST_USER_ID

from basket_api.events import UserCheckoutAcceptedIntegrationEvent

BASKET_BODY = {
    "buyerId": TEST_USER_ID,
    "items": [
        {
            "id": "basket-item-1",
            "productId": 1,
            "productName": ".NET Bot Black Hoodie",
            "unitPrice": 19.5,
            "oldUnitPrice": 0,
            "quantity": 2,
            "pictureUrl": "http://catalog/items/1/pic/",
        }
    ],
}

CHECKOUT_BODY = {
    "city": "Seattle",
    "street": "123 Main St",
    "state": "WA",
    "country": "U.S.",
    "zipCode": "98101",
    "cardNumber": "4012888888881881",
    "cardHolderName": "Alice Smith",
    "cardExpiration": "2025-12-31T00:00:00Z",
    "cardSecurityNumber": "535",
    "cardTypeId": 1,
    "buyer": "alice@eshop",
    "requestId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
}


async def test_all_routes_require_authorization(client):
    responses = [
        await client.get(f"/api/v1/basket/{TEST_USER_ID}"),
        await client.post("/api/v1/basket", json=BASKET_BODY),
        await client.post("/api/v1/basket/checkout", json=CHECKOUT_BODY),
        await client.delete(f"/api/v1/basket/{TEST_USER_ID}"),
    ]
    for response in responses:
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"].startswith("Bearer")
        assert response.content == b""


async def test_get_missing_basket_returns_empty_basket(client, auth_headers):
    response = await client.get(f"/api/v1/basket/{TEST_USER_ID}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"buyerId": TEST_USER_ID, "items": []}


async def test_update_then_get_roundtrip(client, auth_headers):
    update = await client.post("/api/v1/basket", json=BASKET_BODY, headers=auth_headers)
    assert update.status_code == 200
    assert update.json() == BASKET_BODY
    assert update.headers["content-type"] == "application/json; charset=utf-8"

    fetched = await client.get(f"/api/v1/basket/{TEST_USER_ID}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json() == BASKET_BODY


async def test_routes_are_case_insensitive_like_aspnet(client, auth_headers):
    response = await client.get(f"/api/v1/Basket/{TEST_USER_ID}", headers=auth_headers)
    assert response.status_code == 200


async def test_update_with_invalid_quantity_returns_400_messages(client, auth_headers):
    body = json.loads(json.dumps(BASKET_BODY))
    body["items"][0]["quantity"] = 0
    response = await client.post("/api/v1/basket", json=body, headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["messages"] == ["Invalid number of units"]


async def test_checkout_without_basket_returns_400(client, auth_headers):
    response = await client.post("/api/v1/basket/checkout", json=CHECKOUT_BODY, headers=auth_headers)
    assert response.status_code == 400
    assert response.content == b""


async def test_checkout_publishes_user_checkout_accepted(client, auth_headers, event_bus):
    await client.post("/api/v1/basket", json=BASKET_BODY, headers=auth_headers)
    request_id = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/basket/checkout",
        json=CHECKOUT_BODY,
        headers={**auth_headers, "x-requestid": request_id},
    )
    assert response.status_code == 202
    assert response.content == b""

    assert len(event_bus.published) == 1
    event = event_bus.published[0]
    assert isinstance(event, UserCheckoutAcceptedIntegrationEvent)
    assert event.user_id == TEST_USER_ID
    assert event.user_name == "alice@eshop"
    assert str(event.request_id) == request_id  # header wins over the body value
    assert event.basket.buyer_id == TEST_USER_ID
    assert event.basket.items[0].product_id == 1
    assert event.city == "Seattle"
    assert event.card_number == "4012888888881881"


async def test_checkout_uses_body_request_id_when_header_invalid(client, auth_headers, event_bus):
    await client.post("/api/v1/basket", json=BASKET_BODY, headers=auth_headers)
    response = await client.post(
        "/api/v1/basket/checkout",
        json=CHECKOUT_BODY,
        headers={**auth_headers, "x-requestid": "not-a-guid"},
    )
    assert response.status_code == 202
    assert str(event_bus.published[0].request_id) == CHECKOUT_BODY["requestId"]


async def test_checkout_returns_500_when_publish_fails(app, client, auth_headers, event_bus):
    from httpx import ASGITransport, AsyncClient

    await client.post("/api/v1/basket", json=BASKET_BODY, headers=auth_headers)
    event_bus.fail_publish = True
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as raw_client:
        response = await raw_client.post("/api/v1/basket/checkout", json=CHECKOUT_BODY, headers=auth_headers)
    assert response.status_code == 500


async def test_delete_returns_200_with_empty_body(client, auth_headers):
    await client.post("/api/v1/basket", json=BASKET_BODY, headers=auth_headers)
    response = await client.delete(f"/api/v1/basket/{TEST_USER_ID}", headers=auth_headers)
    assert response.status_code == 200
    assert response.content == b""

    fetched = await client.get(f"/api/v1/basket/{TEST_USER_ID}", headers=auth_headers)
    assert fetched.json() == {"buyerId": TEST_USER_ID, "items": []}


async def test_update_binds_pascal_case_body_like_newtonsoft(client, auth_headers):
    pascal = {
        "BuyerId": TEST_USER_ID,
        "Items": [
            {
                "Id": "basket-item-1",
                "ProductId": 1,
                "ProductName": ".NET Bot Black Hoodie",
                "UnitPrice": 19.5,
                "OldUnitPrice": 0,
                "Quantity": 2,
                "PictureUrl": "http://catalog/items/1/pic/",
            }
        ],
    }
    response = await client.post("/api/v1/basket", json=pascal, headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == BASKET_BODY
