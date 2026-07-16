"""Port of the .NET ``Locations.FunctionalTests`` scenarios (the behavioral
oracle) plus response-shape/status-code parity assertions for every frozen
``api/v1/locations`` route."""

from __future__ import annotations

import json

from conftest import TEST_USER_ID


class Get:
    locations = "api/v1/locations"

    @staticmethod
    def location_by(location_id) -> str:
        return f"api/v1/locations/{location_id}"

    @staticmethod
    def user_location_by(user_id: str) -> str:
        return f"api/v1/locations/user/{user_id}"


ADD_NEW_LOCATION = "api/v1/locations/"


async def _create_location(client, longitude: float, latitude: float):
    content = json.dumps({"longitude": longitude, "latitude": latitude})
    return await client.post(
        ADD_NEW_LOCATION, content=content, headers={"Content-Type": "application/json"}
    )


async def _assert_user_location(client, expected_code: str) -> dict:
    user_response = await client.get(Get.user_location_by(TEST_USER_ID))
    assert user_response.status_code == 200
    user_location = user_response.json()

    location_response = await client.get(Get.location_by(user_location["locationId"]))
    assert location_response.status_code == 200
    location = location_response.json()
    assert location["code"] == expected_code
    return user_location


async def test_set_new_user_seattle_location_response_ok(client):
    response = await _create_location(client, -122.315752, 47.604610)
    assert response.status_code == 200
    assert response.content == b""
    await _assert_user_location(client, "SEAT")


async def test_set_new_user_redmond_location_response_ok(client):
    response = await _create_location(client, -122.119998, 47.690876)
    assert response.status_code == 200
    await _assert_user_location(client, "REDM")


async def test_set_new_user_washington_location_response_ok(client):
    response = await _create_location(client, -121.040360, 48.091631)
    assert response.status_code == 200
    await _assert_user_location(client, "WHT")


async def test_get_all_locations_response_ok(client):
    response = await client.get(Get.locations)
    assert response.status_code == 200
    locations = response.json()
    assert len(locations) > 0


async def test_locations_payload_shape_matches_dotnet_camelcase(client):
    response = await client.get(Get.location_by(1))
    assert response.status_code == 200
    payload = response.json()
    assert list(payload.keys()) == [
        "id", "locationId", "code", "parent_Id", "description",
        "latitude", "longitude", "location", "polygon",
    ]
    assert payload["code"] == "NA"
    assert payload["location"]["type"] == "Point"
    assert payload["location"]["coordinates"] == [-103.219329, 48.803281]
    assert payload["polygon"]["type"] == "Polygon"
    assert payload["parent_Id"] is None

    child = (await client.get(Get.location_by(2))).json()
    assert child["parent_Id"] == payload["id"]


async def test_user_location_payload_shape(client):
    await _create_location(client, -122.315752, 47.604610)
    response = await client.get(Get.user_location_by(TEST_USER_ID))
    payload = response.json()
    assert list(payload.keys()) == ["id", "userId", "locationId", "updateDate"]
    assert payload["userId"] == TEST_USER_ID
    assert payload["locationId"] == 4


async def test_unknown_user_location_returns_204(client):
    response = await client.get(Get.user_location_by("11111111-1111-1111-1111-111111111111"))
    assert response.status_code == 204
    assert response.content == b""


async def test_non_guid_user_id_returns_404(client):
    response = await client.get(Get.user_location_by("not-a-guid"))
    assert response.status_code == 404


async def test_unknown_location_id_returns_204(client):
    response = await client.get(Get.location_by(999))
    assert response.status_code == 204


async def test_non_int_location_id_returns_400_problem(client):
    response = await client.get(Get.location_by("abc"))
    assert response.status_code == 400
    payload = response.json()
    assert payload["title"] == "One or more validation errors occurred."
    assert "locationId" in payload["errors"]


async def test_position_outside_all_regions_returns_500_error_body(client):
    response = await _create_location(client, -140.0, 0.0)  # mid-Pacific: no seeded region
    assert response.status_code == 500
    assert response.json()["messages"] == ["An error occur.Try it again."]


async def test_update_existing_user_location_upserts_single_document(client, repository):
    await _create_location(client, -122.315752, 47.604610)  # SEAT
    first = (await client.get(Get.user_location_by(TEST_USER_ID))).json()
    await _create_location(client, -122.119998, 47.690876)  # REDM
    second = (await client.get(Get.user_location_by(TEST_USER_ID))).json()
    assert first["id"] == second["id"]  # replaced, not duplicated
    assert second["locationId"] == 5
    assert len(repository.user_locations) == 1


async def test_post_publishes_user_location_updated_event(client, event_bus):
    await _create_location(client, -122.315752, 47.604610)
    assert len(event_bus.published) == 1
    event = event_bus.published[0]
    assert type(event).event_name() == "UserLocationUpdatedIntegrationEvent"
    payload = json.loads(event.to_json())
    assert payload["UserId"] == TEST_USER_ID
    # Nearest region first, exactly the regions containing the point.
    assert [entry["Code"] for entry in payload["LocationList"]] == ["SEAT", "WHT", "NA", "US"]
    assert list(payload.keys()) == ["UserId", "LocationList", "Id", "CreationDate"]
    assert list(payload["LocationList"][0].keys()) == ["LocationId", "Code", "Description"]


async def test_routes_tolerate_dotnet_casing_and_trailing_slash(client):
    assert (await client.get("api/v1/Locations")).status_code == 200
    assert (await client.get("api/v1/Locations/")).status_code == 200
    assert (await client.get("api/v1/Locations/1")).status_code == 200


async def test_requests_require_authorization(location_settings, repository, event_bus):
    from eshop_common.health.core import HealthCheckRegistry
    from fastapi import HTTPException
    from httpx import ASGITransport, AsyncClient

    from locations_api.app import create_app
    from locations_api.service import LocationsService

    async def deny(request):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})

    app = create_app(
        location_settings,
        LocationsService(repository, event_bus),
        HealthCheckRegistry(),
        authenticator=deny,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as anon:
        for url in (Get.locations, Get.location_by(1), Get.user_location_by(TEST_USER_ID)):
            response = await anon.get(url)
            assert response.status_code == 401
            assert response.headers.get("WWW-Authenticate") == "Bearer"
        response = await anon.post(ADD_NEW_LOCATION, json={"longitude": 0, "latitude": 0})
        assert response.status_code == 401
