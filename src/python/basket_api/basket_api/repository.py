"""Redis basket repository, port of ``RedisBasketRepository``.

Keys are the raw buyer ids and values the PascalCase Newtonsoft JSON written by
the .NET implementation, so entries stay fully interchangeable between stacks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import redis.asyncio as aioredis

from basket_api.models import CustomerBasket


class RedisBasketRepository:
    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client

    async def get_basket(self, customer_id: str) -> CustomerBasket | None:
        data = await self._client.get(customer_id)
        if data is None:
            return None
        return CustomerBasket.from_redis_json(data)

    async def update_basket(self, basket: CustomerBasket) -> CustomerBasket | None:
        if basket.buyer_id is None:
            # StackExchange.Redis throws on a null key; surfaces as a 500.
            raise ValueError("BuyerId is required")
        created = await self._client.set(basket.buyer_id, basket.to_redis_json())
        if not created:
            return None
        return await self.get_basket(basket.buyer_id)

    async def delete_basket(self, customer_id: str) -> bool:
        return bool(await self._client.delete(customer_id))

    async def get_users(self) -> AsyncIterator[str]:
        """Port of ``GetUsers`` (SERVER KEYS enumeration)."""
        async for key in self._client.scan_iter(match="*"):
            yield key.decode("utf-8") if isinstance(key, bytes) else str(key)
