"""Outbound webhook delivery, a port of ``WebhooksSender``/``WebhookData``.

The callback body is Newtonsoft-serialized ``WebhookData`` (PascalCase, in
declaration order ``When``, ``Payload``, ``Type``) where ``Payload`` is itself
the Newtonsoft JSON of the consumer-side integration event. Deliveries run
concurrently and, like the .NET sender, are NOT retried: the outbound delivery
contract is a single POST per subscription per received event (at-least-once
end to end because the broker may redeliver). Failures are logged and observable
without introducing extra attempts.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import structlog
from eshop_common.events import IntegrationEvent, dumps_newtonsoft

from webhooks_api.models import WebhookSubscription, WebhookType

logger = structlog.get_logger(__name__)

TOKEN_HEADER = "X-eshop-whtoken"


class WebhookData:
    """Port of ``WebhookData``: captures ``When`` at construction and serializes
    the event with Newtonsoft semantics into the ``Payload`` string."""

    def __init__(self, hook_type: WebhookType, data: IntegrationEvent) -> None:
        self.when = datetime.now(UTC)
        self.type = hook_type.name
        self.payload = dumps_newtonsoft(data)

    def to_json(self) -> str:
        return dumps_newtonsoft({"When": self.when, "Payload": self.payload, "Type": self.type})


class WebhooksSender:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def send_all(self, receivers: list[WebhookSubscription], data: WebhookData) -> None:
        import asyncio

        json_body = data.to_json()
        await asyncio.gather(
            *(self._send(subscription, json_body) for subscription in receivers),
            return_exceptions=True,
        )

    async def _send(self, subscription: WebhookSubscription, json_body: str) -> None:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if subscription.Token and subscription.Token.strip():
            headers[TOKEN_HEADER] = subscription.Token
        logger.debug("sending_hook", dest_url=subscription.DestUrl, type=subscription.Type)
        try:
            response = await self._client.post(
                subscription.DestUrl or "", content=json_body.encode("utf-8"), headers=headers
            )
            logger.info(
                "hook_sent",
                dest_url=subscription.DestUrl,
                status_code=response.status_code,
                subscription_id=subscription.Id,
            )
        except httpx.HTTPError as exc:
            # Same as the .NET sender's unawaited-task behavior: a failed POST
            # is not retried and must not fail the other deliveries.
            logger.warning(
                "hook_send_failed",
                dest_url=subscription.DestUrl,
                subscription_id=subscription.Id,
                error=type(exc).__name__,
            )
