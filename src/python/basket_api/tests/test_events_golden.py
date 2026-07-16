"""Byte-for-byte serialization parity with the frozen event goldens, plus
routing-key naming and tolerant consumption of producer payloads."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from basket_api.events import (
    OrderStartedIntegrationEvent,
    ProductPriceChangedIntegrationEvent,
    UserCheckoutAcceptedIntegrationEvent,
)
from basket_api.models import BasketItem, CustomerBasket

GOLDEN_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"
PINNED_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
PINNED_DATE = datetime(2020, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)


def golden(name: str) -> str:
    return (GOLDEN_DIR / f"{name}.golden.json").read_text(encoding="utf-8").strip()


def test_user_checkout_accepted_matches_golden():
    basket = CustomerBasket(
        BuyerId="alice@eshop",
        Items=[
            BasketItem(
                Id="basket-item-1",
                ProductId=1,
                ProductName=".NET Bot Black Hoodie",
                UnitPrice=Decimal("19.50"),
                OldUnitPrice=Decimal("18.00"),
                Quantity=2,
                PictureUrl="http://externalcatalogbaseurltobereplaced/c/api/v1/catalog/items/1/pic/",
            )
        ],
    )
    event = UserCheckoutAcceptedIntegrationEvent(
        UserId="e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5",
        UserName="alice@eshop",
        OrderNumber=0,
        City="Seattle",
        Street="123 Main St",
        State="WA",
        Country="U.S.",
        ZipCode="98101",
        CardNumber="4012888888881881",
        CardHolderName="Alice Smith",
        CardExpiration=datetime(2025, 12, 31, tzinfo=UTC),
        CardSecurityNumber="535",
        CardTypeId=1,
        Buyer="alice@eshop",
        RequestId=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        Basket=basket,
        Id=PINNED_ID,
        CreationDate=PINNED_DATE,
    )
    assert event.to_json() == golden("UserCheckoutAcceptedIntegrationEvent")
    assert type(event).event_name() == "UserCheckoutAcceptedIntegrationEvent"  # routing key
    assert type(event).service_bus_label() == "UserCheckoutAccepted"


def test_consumed_events_parse_dotnet_producer_payloads():
    price_changed = ProductPriceChangedIntegrationEvent.from_json(golden("ProductPriceChangedIntegrationEvent"))
    assert price_changed.product_id == 1
    assert price_changed.new_price == Decimal("21.50")
    assert price_changed.old_price == Decimal("19.50")
    assert price_changed.id == PINNED_ID

    order_started = OrderStartedIntegrationEvent.from_json(golden("OrderStartedIntegrationEvent"))
    assert order_started.user_id == "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5"
    assert type(order_started).event_name() == "OrderStartedIntegrationEvent"
