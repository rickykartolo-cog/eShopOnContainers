"""Integration-event consumers, ports of the .NET handlers.

- ``ProductPriceChangedIntegrationEvent`` → for every stored basket, update
  items whose ``UnitPrice`` equals the event's old price: set ``UnitPrice`` to
  the new price and ``OldUnitPrice`` to the previous unit price (exactly the
  .NET ``ProductPriceChangedIntegrationEventHandler`` behavior).
- ``OrderStartedIntegrationEvent`` → delete the buyer's basket.

Duplicate delivery produces no additional side effects (§6.3.7): both handlers
are naturally idempotent, matching the reference implementation. Re-applying a
price change is a no-op (items already at the new price no longer match the old
price), and deleting an absent basket is a no-op.
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from eshop_common.eventbus.base import EventBus

from basket_api.events import OrderStartedIntegrationEvent, ProductPriceChangedIntegrationEvent
from basket_api.models import CustomerBasket
from basket_api.repository import RedisBasketRepository

logger = structlog.get_logger(__name__)


class BasketEventConsumers:
    def __init__(self, repository: RedisBasketRepository, event_bus: EventBus) -> None:
        self._repository = repository
        self._event_bus = event_bus

    async def subscribe_all(self) -> None:
        await self._event_bus.subscribe(ProductPriceChangedIntegrationEvent, self.on_product_price_changed)
        await self._event_bus.subscribe(OrderStartedIntegrationEvent, self.on_order_started)

    async def on_product_price_changed(self, event) -> None:
        assert isinstance(event, ProductPriceChangedIntegrationEvent)
        logger.info("handling_product_price_changed", event_id=str(event.id), product_id=event.product_id)
        async for user_id in self._repository.get_users():
            basket = await self._repository.get_basket(user_id)
            await self._update_price_in_basket_items(event.product_id, event.new_price, event.old_price, basket)

    async def _update_price_in_basket_items(
        self, product_id: int, new_price: Decimal, old_price: Decimal, basket: CustomerBasket | None
    ) -> None:
        if basket is None or basket.items is None:
            return
        # The .NET handler rewrites the basket whenever Items is non-null, even
        # when no item matched; keep that exact write behavior.
        items_to_update = [item for item in basket.items if item.product_id == product_id]
        for item in items_to_update:
            if item.unit_price == old_price:
                original_price = item.unit_price
                item.unit_price = new_price
                item.old_unit_price = original_price
        await self._repository.update_basket(basket)

    async def on_order_started(self, event) -> None:
        assert isinstance(event, OrderStartedIntegrationEvent)
        logger.info("handling_order_started", event_id=str(event.id), user_id=event.user_id)
        await self._repository.delete_basket(str(event.user_id))
