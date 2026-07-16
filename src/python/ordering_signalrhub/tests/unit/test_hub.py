import jwt as pyjwt
import pytest
import socketio
from eshop_common.auth import OidcJwtValidator

from ordering_signalrhub.events import OrderStatusChangedToShippedIntegrationEvent
from ordering_signalrhub.handlers import make_handler
from ordering_signalrhub.hub import (
    HUB_PATH,
    UPDATED_ORDER_STATE,
    NotificationHub,
    extract_access_token,
    resolve_user_name,
)

from ..conftest import contracts_events_dir, make_token


def test_hub_path_frozen():
    assert HUB_PATH == "/hub/notificationhub"


def test_access_token_from_query_string():
    environ = {"QUERY_STRING": "access_token=abc123&EIO=4&transport=websocket"}
    assert extract_access_token(environ, None) == "abc123"


def test_access_token_from_auth_payload_preferred():
    environ = {"QUERY_STRING": "access_token=from-query"}
    assert extract_access_token(environ, {"access_token": "from-auth"}) == "from-auth"
    assert extract_access_token({"QUERY_STRING": ""}, {"token": "t"}) == "t"


def test_missing_token_returns_none():
    assert extract_access_token({"QUERY_STRING": ""}, None) is None


def test_resolve_user_name_prefers_unique_name():
    assert resolve_user_name({"unique_name": "alice", "name": "Alice A"}) == "alice"
    assert resolve_user_name({"name": "Alice A"}) == "Alice A"
    assert resolve_user_name({"preferred_username": "alice"}) == "alice"
    assert resolve_user_name({"sub": "id"}) is None


@pytest.fixture
def hub(idp):
    return NotificationHub(OidcJwtValidator(authority=idp, audience="orders.signalrhub"))


async def test_connect_without_token_refused(hub):
    with pytest.raises(socketio.exceptions.ConnectionRefusedError):
        await hub._on_connect("sid1", {"QUERY_STRING": ""}, None)


async def test_connect_with_invalid_token_refused(hub):
    with pytest.raises(socketio.exceptions.ConnectionRefusedError):
        await hub._on_connect("sid1", {"QUERY_STRING": "access_token=not-a-jwt"}, None)


async def test_connect_with_wrong_audience_refused(hub, idp):
    token = make_token(idp, audience="orders")
    with pytest.raises(socketio.exceptions.ConnectionRefusedError):
        await hub._on_connect("sid1", {"QUERY_STRING": f"access_token={token}"}, None)


async def test_connect_without_user_name_claim_refused(hub, idp):
    token = make_token(idp, user_name=None)
    with pytest.raises(socketio.exceptions.ConnectionRefusedError):
        await hub._on_connect("sid1", {"QUERY_STRING": f"access_token={token}"}, None)


async def test_connect_joins_room_keyed_by_user_name(hub, idp, monkeypatch):
    joined = []

    async def fake_enter_room(sid, room):
        joined.append((sid, room))

    saved = {}

    async def fake_save_session(sid, session):
        saved[sid] = session

    monkeypatch.setattr(hub.sio, "enter_room", fake_enter_room)
    monkeypatch.setattr(hub.sio, "save_session", fake_save_session)
    token = make_token(idp, user_name="alice@eshop")
    await hub._on_connect("sid1", {"QUERY_STRING": f"access_token={token}"}, None)
    assert joined == [("sid1", "alice@eshop")]
    assert saved["sid1"] == {"user_name": "alice@eshop"}


async def test_handler_emits_updated_order_state_to_buyer_room(hub, monkeypatch):
    emitted = []

    async def fake_emit(event, data=None, room=None, **kwargs):
        emitted.append((event, data, room))

    monkeypatch.setattr(hub.sio, "emit", fake_emit)
    golden = (
        contracts_events_dir() / "OrderStatusChangedToShippedIntegrationEvent.golden.json"
    ).read_text()
    event = OrderStatusChangedToShippedIntegrationEvent.from_json(golden)

    await make_handler(hub)(event)

    # camelCase payload: exactly what the SignalR JSON protocol delivered to the browser.
    assert emitted == [(UPDATED_ORDER_STATE, {"orderId": 42, "status": "shipped"}, "alice@eshop")]


def test_expired_token_rejected_type(idp):
    token = make_token(idp, exp_offset=-100)
    with pytest.raises(pyjwt.PyJWTError):
        pyjwt.decode(token, options={"verify_signature": False, "verify_exp": True})
