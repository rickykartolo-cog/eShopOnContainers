"""HTTP functional tests: ports of ``Marketing.FunctionalTests/CampaignScenarios``
and ``UserLocationRoleScenarios`` plus route-semantics coverage (status codes,
Location headers, DTO shapes, picture URI behavior, authorization, pic route)."""

from urllib.parse import urlparse

INT32_MAX = 2_147_483_647

CAMPAIGN_BODY = {
    "name": "FakeCampaignName",
    "description": "FakeCampaignDescription",
    "from": "2021-01-01T00:00:00",
    "to": "2021-02-01T00:00:00",
    "pictureUri": "http://externalcatalogbaseurltobereplaced/api/v1/campaigns/1/pic",
}

LOCATION_RULE_BODY = {"locationId": 20, "description": "FakeUserLocationRuleDescription"}


async def test_get_all_campaigns_ok(client):
    response = await client.get("/api/v1/campaigns")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 2
    assert list(body[0].keys()) == ["id", "name", "description", "from", "to", "pictureUri", "detailsUri"]
    assert body[0]["pictureUri"] == "http://localhost:5110/api/v1/campaigns/1/pic/"
    assert body[0]["detailsUri"] is None


async def test_get_campaign_by_id_ok(client):
    response = await client.get("/api/v1/campaigns/2")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 2
    assert body["name"] == "Roslyn Red T-Shirt 3x2"
    assert body["pictureUri"] == "http://localhost:5110/api/v1/campaigns/2/pic/"


async def test_get_campaign_by_id_not_found(client):
    response = await client.get(f"/api/v1/campaigns/{INT32_MAX}")
    assert response.status_code == 404
    assert response.content == b""


async def test_get_campaign_by_noninteger_id_route_mismatch(client):
    response = await client.get("/api/v1/campaigns/abc")
    assert response.status_code == 404


async def test_routes_are_case_insensitive(client):
    response = await client.get("/api/v1/Campaigns/2")
    assert response.status_code == 200


async def test_post_campaign_created_with_location_header(client):
    response = await client.post("/api/v1/campaigns", json=CAMPAIGN_BODY)
    assert response.status_code == 201
    assert response.content == b""
    location = urlparse(response.headers["Location"])
    assert location.path.startswith("/api/v1/Campaigns/")
    new_id = int(location.path.rsplit("/", 1)[1])

    fetched = await client.get(f"/api/v1/campaigns/{new_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "FakeCampaignName"


async def test_put_campaign_returns_created(client):
    response = await client.put("/api/v1/campaigns/2", json=CAMPAIGN_BODY)
    assert response.status_code == 201
    location = urlparse(response.headers["Location"])
    assert location.path == "/api/v1/Campaigns/2"

    fetched = await client.get("/api/v1/campaigns/2")
    assert fetched.json()["name"] == "FakeCampaignName"
    assert fetched.json()["from"] == "2021-01-01T00:00:00"


async def test_put_campaign_not_found(client):
    response = await client.put(f"/api/v1/campaigns/{INT32_MAX}", json=CAMPAIGN_BODY)
    assert response.status_code == 404


async def test_put_campaign_invalid_id_bad_request(client):
    response = await client.put("/api/v1/campaigns/0", json=CAMPAIGN_BODY)
    assert response.status_code == 400


async def test_delete_campaign_no_content(client):
    created = await client.post("/api/v1/campaigns", json=CAMPAIGN_BODY)
    new_id = int(urlparse(created.headers["Location"]).path.rsplit("/", 1)[1])

    response = await client.delete(f"/api/v1/campaigns/{new_id}")
    assert response.status_code == 204
    assert response.content == b""

    fetched = await client.get(f"/api/v1/campaigns/{new_id}")
    assert fetched.status_code == 404


async def test_delete_campaign_not_found(client):
    response = await client.delete(f"/api/v1/campaigns/{INT32_MAX}")
    assert response.status_code == 404


async def test_delete_campaign_invalid_id_bad_request(client):
    response = await client.delete("/api/v1/campaigns/0")
    assert response.status_code == 400


async def test_get_locations_by_campaign_ok(client):
    response = await client.get("/api/v1/campaigns/1/locations")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert list(body[0].keys()) == ["id", "locationId", "description"]
    assert body[0]["locationId"] == 1


async def test_get_locations_invalid_campaign_bad_request(client):
    response = await client.get("/api/v1/campaigns/0/locations")
    assert response.status_code == 400


async def test_get_location_rule_by_id_ok(client):
    response = await client.get("/api/v1/campaigns/2/locations/2")
    assert response.status_code == 200
    body = response.json()
    assert body == {"id": 2, "locationId": 3, "description": "Campaign is only for Seattle users."}


async def test_get_location_rule_not_found(client):
    response = await client.get(f"/api/v1/campaigns/2/locations/{INT32_MAX}")
    assert response.status_code == 404


async def test_get_location_rule_invalid_ids_bad_request(client):
    assert (await client.get("/api/v1/campaigns/0/locations/1")).status_code == 400
    assert (await client.get("/api/v1/campaigns/1/locations/0")).status_code == 400


async def test_post_location_rule_created_then_delete_no_content(client):
    response = await client.post("/api/v1/campaigns/2/locations", json=LOCATION_RULE_BODY)
    assert response.status_code == 201
    path = urlparse(response.headers["Location"]).path
    assert path.startswith("/api/v1/campaigns/2/locations/")
    rule_id = int(path.rsplit("/", 1)[1])

    fetched = await client.get(f"/api/v1/campaigns/2/locations/{rule_id}")
    assert fetched.status_code == 200
    assert fetched.json()["locationId"] == 20
    assert fetched.json()["description"] == "FakeUserLocationRuleDescription"

    deleted = await client.delete(f"/api/v1/campaigns/2/locations/{rule_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/campaigns/2/locations/{rule_id}")).status_code == 404


async def test_delete_location_rule_not_found(client):
    response = await client.delete(f"/api/v1/campaigns/2/locations/{INT32_MAX}")
    assert response.status_code == 404


async def test_get_pic_is_anonymous_and_serves_png(anonymous_client, marketing_settings, tmp_path):
    png = b"\x89PNG\r\n\x1a\n fake"
    (tmp_path / "1.png").write_bytes(png)
    marketing_settings.settings._values["pics_path"] = str(tmp_path)
    response = await anonymous_client.get("/api/v1/campaigns/1/pic")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == png


async def test_campaign_routes_require_authentication(anonymous_client):
    for method, url in [
        ("GET", "/api/v1/campaigns"),
        ("GET", "/api/v1/campaigns/1"),
        ("POST", "/api/v1/campaigns"),
        ("PUT", "/api/v1/campaigns/1"),
        ("DELETE", "/api/v1/campaigns/1"),
        ("GET", "/api/v1/campaigns/user"),
        ("GET", "/api/v1/campaigns/1/locations"),
        ("GET", "/api/v1/campaigns/1/locations/1"),
        ("POST", "/api/v1/campaigns/1/locations"),
        ("DELETE", "/api/v1/campaigns/1/locations/1"),
    ]:
        response = await anonymous_client.request(method, url, json={})
        assert response.status_code == 401, (method, url)
        assert response.headers.get("WWW-Authenticate") == "Bearer"


async def test_user_campaigns_empty_without_marketing_data(client):
    response = await client.get("/api/v1/campaigns/user")
    assert response.status_code == 200
    assert response.json() == {"pageIndex": 0, "pageSize": 10, "count": 0, "data": []}


async def test_user_campaigns_matches_user_locations(client, repository):
    from marketing_api.read_model import Location, MarketingData

    await repository.update_location(
        MarketingData(UserId="1234", Locations=[Location(LocationId=3, Code="SEAT", Description="Seattle")])
    )
    response = await client.get("/api/v1/campaigns/user")
    body = response.json()
    assert body["count"] == 1
    assert body["pageIndex"] == 0 and body["pageSize"] == 10
    assert body["data"][0]["id"] == 2
    assert body["data"][0]["name"] == "Roslyn Red T-Shirt 3x2"


async def test_user_campaigns_pagination(client, repository):
    from marketing_api.read_model import Location, MarketingData

    await repository.update_location(
        MarketingData(
            UserId="1234",
            Locations=[Location(LocationId=1), Location(LocationId=3)],
        )
    )
    response = await client.get("/api/v1/campaigns/user?pageSize=1&pageIndex=1")
    body = response.json()
    assert body["count"] == 2
    assert body["pageIndex"] == 1 and body["pageSize"] == 1
    assert len(body["data"]) == 1


async def test_user_campaigns_invalid_paging_bad_request(client):
    response = await client.get("/api/v1/campaigns/user?pageSize=abc")
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_details_uri_composed_from_function_uri(marketing_settings, seeded_session_factory, repository):
    from eshop_common.health.core import HealthCheckRegistry
    from httpx import ASGITransport, AsyncClient

    from marketing_api.app import create_app

    marketing_settings.settings._values["campaigndetailfunctionuri"] = "http://func/api/campaigns?code=x"

    async def user(_request):
        return "1234"

    app = create_app(
        marketing_settings, seeded_session_factory, HealthCheckRegistry(), repository, user_resolver=user
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        response = await http_client.get("/api/v1/campaigns/1")
    assert response.json()["detailsUri"] == "http://func/api/campaigns?code=x&campaignId=1&userId=1234"


async def test_azure_storage_enabled_picture_uri(marketing_settings, seeded_session_factory, repository):
    from eshop_common.health.core import HealthCheckRegistry
    from httpx import ASGITransport, AsyncClient

    from marketing_api.app import create_app

    marketing_settings.settings._values["azurestorageenabled"] = "True"
    marketing_settings.settings._values["picbaseurl"] = "https://storage.blob.core.windows.net/pics/"

    async def user(_request):
        return "1234"

    app = create_app(
        marketing_settings, seeded_session_factory, HealthCheckRegistry(), repository, user_resolver=user
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        response = await http_client.get("/api/v1/campaigns/1")
    assert response.json()["pictureUri"] == "https://storage.blob.core.windows.net/pics/1.png"
