"""Mixed-stack realtime journey against a real RabbitMQ broker.

Simulates the .NET Ordering.API producer by publishing the exact golden
Newtonsoft.Json bytes (persistent, direct exchange ``eshop_event_bus``,
routing key = event class name) and asserts a real Socket.IO browser client —
authenticated via ``access_token`` in the query string — receives
``UpdatedOrderState { orderId, status }``, and that other users' rooms do not.
"""

import asyncio
import contextlib
import socket

import aio_pika
import pytest
import socketio
import uvicorn
from eshop_common.config import Settings
from eshop_common.testing import rabbitmq_host

from ordering_signalrhub.events import ORDER_STATUS_EVENTS
from ordering_signalrhub.hub import HUB_PATH
from ordering_signalrhub.main import build_app

from ..conftest import contracts_events_dir, make_token

pytestmark = pytest.mark.integration

EXCHANGE = "eshop_event_bus"
QUEUE = "Ordering.signalrhub"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def running_hub(idp):
    port = _free_port()
    app = build_app(
        settings=Settings(
            {
                "EventBusConnection": rabbitmq_host(),
                "identityUrl": idp,
                "SubscriptionClientName": QUEUE,
            }
        )
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=10)


async def _publish_golden(event_name: str) -> None:
    connection = await aio_pika.connect(host=rabbitmq_host())
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=False)
        body = (contracts_events_dir() / f"{event_name}.golden.json").read_bytes().strip()
        await exchange.publish(
            aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=event_name,
        )


async def _connect_client(base_url: str, token: str) -> tuple[socketio.AsyncClient, list]:
    client = socketio.AsyncClient()
    received: list = []

    @client.on("UpdatedOrderState")
    async def on_update(msg):
        received.append(msg)

    await client.connect(
        f"{base_url}{HUB_PATH}?access_token={token}",
        socketio_path=HUB_PATH,
        transports=["websocket", "polling"],
    )
    return client, received


@pytest.mark.parametrize("event_type", ORDER_STATUS_EVENTS, ids=lambda t: t.__name__)
async def test_dotnet_producer_to_socketio_client(running_hub, idp, event_type):
    token = make_token(idp, user_name="alice@eshop")
    client, received = await _connect_client(running_hub, token)
    try:
        await _publish_golden(event_type.event_name())
        for _ in range(100):
            if received:
                break
            await asyncio.sleep(0.1)
        golden_status = event_type.from_json(
            (contracts_events_dir() / f"{event_type.event_name()}.golden.json").read_text()
        ).order_status
        assert received == [{"orderId": 42, "status": golden_status}]
    finally:
        await client.disconnect()


async def test_other_users_do_not_receive_the_message(running_hub, idp):
    alice, alice_received = await _connect_client(running_hub, make_token(idp, user_name="alice@eshop"))
    bob, bob_received = await _connect_client(running_hub, make_token(idp, user_name="bob@eshop"))
    try:
        await _publish_golden("OrderStatusChangedToShippedIntegrationEvent")
        for _ in range(100):
            if alice_received:
                break
            await asyncio.sleep(0.1)
        assert alice_received == [{"orderId": 42, "status": "shipped"}]
        await asyncio.sleep(1)
        assert bob_received == []
    finally:
        await alice.disconnect()
        await bob.disconnect()


async def test_unauthenticated_connection_refused(running_hub):
    client = socketio.AsyncClient()
    with pytest.raises(socketio.exceptions.ConnectionError):
        await client.connect(
            f"{running_hub}{HUB_PATH}",
            socketio_path=HUB_PATH,
            transports=["polling"],
        )


async def test_health_endpoints_alongside_hub(running_hub):
    import httpx

    async with httpx.AsyncClient() as http:
        liveness = await http.get(f"{running_hub}/liveness")
        assert liveness.status_code == 200
        assert liveness.text == "Healthy"
        hc = await http.get(f"{running_hub}/hc")
        assert hc.status_code == 200
        body = hc.json()
        assert body["status"] == "Healthy"
        assert set(body["entries"]) == {"self", "signalr-rabbitmqbus-check"}
