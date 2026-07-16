"""HTTP functional tests authored from the frozen OpenAPI/routes and the
observed .NET ``WebhooksController`` behavior (master prompt §6.1 note: Webhooks
has no baseline functional-test project). Covers authorization, subscription
ownership, validation and the grant-URL verification flow, status codes,
response bodies/casing, and the 201 Location header used by WebhookClient."""

from __future__ import annotations

import json

from conftest import auth

from webhooks_api.sender import TOKEN_HEADER

VALID_BODY = {
    "url": "http://webhooks-client/hooks",
    "token": "s3cr3t",
    "event": "OrderPaid",
    "grantUrl": "http://webhooks-client/grant-ok",
}


async def test_routes_require_authorization(client):
    for method, path in (
        ("GET", "/api/v1/webhooks"),
        ("GET", "/api/v1/webhooks/1"),
        ("POST", "/api/v1/webhooks"),
        ("DELETE", "/api/v1/webhooks/1"),
    ):
        response = await client.request(method, path)
        assert response.status_code == 401, (method, path)
        assert "WWW-Authenticate" in response.headers
        assert response.content == b""


async def test_list_by_user_empty(client):
    response = await client.get("/api/v1/webhooks", headers=auth())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == []


async def test_subscribe_created_shape_and_location(client):
    response = await client.post("/api/v1/webhooks", json=VALID_BODY, headers=auth())
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "type", "date", "destUrl", "token", "userId"}
    assert body["type"] == 3  # OrderPaid, numeric enum like System.Text.Json
    assert body["destUrl"] == VALID_BODY["url"]
    assert body["token"] == "s3cr3t"
    assert body["userId"] == "alice"
    assert body["date"].endswith("Z")
    assert response.headers["Location"] == f"http://testserver/api/v1/Webhooks/{body['id']}"


async def test_subscribe_event_name_case_insensitive(client):
    response = await client.post(
        "/api/v1/webhooks", json={**VALID_BODY, "event": "orderpaid"}, headers=auth()
    )
    assert response.status_code == 201
    assert response.json()["type"] == 3


async def test_subscription_ownership(client):
    created = await client.post("/api/v1/webhooks", json=VALID_BODY, headers=auth("token-alice"))
    sub_id = created.json()["id"]

    mine = await client.get(f"/api/v1/webhooks/{sub_id}", headers=auth("token-alice"))
    assert mine.status_code == 200
    assert mine.json()["id"] == sub_id

    other = await client.get(f"/api/v1/webhooks/{sub_id}", headers=auth("token-bob"))
    assert other.status_code == 404
    assert other.headers["content-type"].startswith("text/plain")
    assert other.text == f"Subscriptions {sub_id} not found"

    other_list = await client.get("/api/v1/webhooks", headers=auth("token-bob"))
    assert other_list.json() == []

    other_delete = await client.delete(f"/api/v1/webhooks/{sub_id}", headers=auth("token-bob"))
    assert other_delete.status_code == 404


async def test_get_not_found_plain_text_body(client):
    response = await client.get("/api/v1/webhooks/99", headers=auth())
    assert response.status_code == 404
    assert response.text == "Subscriptions 99 not found"


async def test_int_route_constraint_mismatch_is_404(client):
    for method in ("GET", "DELETE"):
        response = await client.request(method, "/api/v1/webhooks/not-a-number", headers=auth())
        assert response.status_code == 404
        assert response.content == b""


async def test_validation_problem_shape(client):
    response = await client.post(
        "/api/v1/webhooks",
        json={"url": "not a url", "event": "NoSuchEvent", "grantUrl": "also bad"},
        headers=auth(),
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "https://tools.ietf.org/html/rfc7231#section-6.5.1"
    assert body["title"] == "One or more validation errors occurred."
    assert body["status"] == 400
    assert "traceId" in body
    assert body["errors"]["GrantUrl"] == ["GrantUrl is not valid"]
    assert body["errors"]["Url"] == ["Url is not valid"]
    assert body["errors"]["Event"] == ["NoSuchEvent is invalid event name"]


async def test_validation_problem_missing_fields(client):
    response = await client.post("/api/v1/webhooks", json={}, headers=auth())
    assert response.status_code == 400
    errors = response.json()["errors"]
    assert errors["GrantUrl"] == ["GrantUrl is not valid"]
    assert errors["Url"] == ["Url is not valid"]
    assert errors["Event"] == [" is invalid event name"]


async def test_grant_url_must_echo_token_418(client, transport):
    response = await client.post(
        "/api/v1/webhooks",
        json={**VALID_BODY, "grantUrl": "http://webhooks-client/grant-noecho"},
        headers=auth(),
    )
    assert response.status_code == 418
    assert response.text == "Grant url can't be validated"
    # The verification used an OPTIONS request carrying the token header.
    options = [r for r in transport.requests if r.method == "OPTIONS"]
    assert options and options[-1].headers[TOKEN_HEADER] == "s3cr3t"


async def test_grant_url_without_token_succeeds_when_no_echo(client):
    body = {**VALID_BODY, "grantUrl": "http://webhooks-client/grant-noecho"}
    body.pop("token")
    response = await client.post("/api/v1/webhooks", json=body, headers=auth())
    assert response.status_code == 201
    assert response.json()["token"] is None


async def test_grant_url_different_origin_418(client):
    response = await client.post(
        "/api/v1/webhooks",
        json={**VALID_BODY, "grantUrl": "https://webhooks-client:8443/grant-ok"},
        headers=auth(),
    )
    assert response.status_code == 418


async def test_grant_url_error_status_418(client):
    response = await client.post(
        "/api/v1/webhooks",
        json={**VALID_BODY, "grantUrl": "http://webhooks-client/grant-fail"},
        headers=auth(),
    )
    assert response.status_code == 418


async def test_unsubscribe_accepted_then_gone(client):
    created = await client.post("/api/v1/webhooks", json=VALID_BODY, headers=auth())
    sub_id = created.json()["id"]

    deleted = await client.delete(f"/api/v1/webhooks/{sub_id}", headers=auth())
    assert deleted.status_code == 202
    assert deleted.content == b""

    gone = await client.get(f"/api/v1/webhooks/{sub_id}", headers=auth())
    assert gone.status_code == 404


async def test_route_casing_insensitive(client):
    response = await client.get("/api/v1/Webhooks", headers=auth())
    assert response.status_code == 200


async def test_home_redirects_to_swagger(client):
    response = await client.get("/")
    assert response.status_code == 302
    assert response.headers["location"].endswith("/swagger")


async def test_serialized_body_bytes_are_stj_shaped(client):
    created = await client.post("/api/v1/webhooks", json=VALID_BODY, headers=auth())
    raw = created.content.decode("utf-8")
    parsed = json.loads(raw)
    # Property order matches the .NET model declaration (camelCased).
    assert list(parsed) == ["id", "type", "date", "destUrl", "token", "userId"]
    assert '"type":3' in raw
