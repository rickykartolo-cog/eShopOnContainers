import json

from fastapi.testclient import TestClient
from pydantic import BaseModel

from eshop_common.config import ServiceSettings, Settings
from eshop_common.template import create_service_app


def make_app(**env: str):
    settings = ServiceSettings(Settings(env))
    return create_service_app("Catalog.API", settings=settings)


def test_openapi_served_at_swagger_v1_swagger_json():
    client = TestClient(make_app())
    response = client.get("/swagger/v1/swagger.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "eShopOnContainers - Catalog.API"
    assert "/hc" not in document.get("paths", {})
    assert "/liveness" not in document.get("paths", {})


def test_health_endpoints_exposed():
    client = TestClient(make_app())
    liveness = client.get("/liveness")
    assert liveness.status_code == 200
    assert liveness.text == "Healthy"

    hc = client.get("/hc")
    assert hc.status_code == 200
    body = hc.json()
    assert list(body) == ["status", "totalDuration", "entries"]
    assert "self" in body["entries"]
    assert hc.headers["content-type"].startswith("application/json")
    assert hc.headers["cache-control"] == "no-store, no-cache"
    assert hc.headers["pragma"] == "no-cache"


def test_validation_errors_return_400_like_aspnetcore():
    app = make_app()

    class Item(BaseModel):
        name: str
        price: float

    @app.post("/api/v1/items")
    async def create_item(item: Item):
        return item

    client = TestClient(app)
    response = client.post("/api/v1/items", content=json.dumps({"name": 1}))
    assert response.status_code == 400


def test_startup_and_shutdown_hooks_run():
    calls: list[str] = []

    async def on_startup(_app):
        calls.append("startup")

    async def on_shutdown(_app):
        calls.append("shutdown")

    app = create_service_app(
        "Basket.API",
        settings=ServiceSettings(Settings({})),
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    with TestClient(app):
        assert calls == ["startup"]
    assert calls == ["startup", "shutdown"]


def test_path_base_sets_root_path():
    app = make_app(PATH_BASE="/catalog-api")
    assert app.root_path == "/catalog-api"


def test_port_settings_default_to_compose_contract():
    settings = ServiceSettings(Settings({}))
    assert settings.http_port == 80
    assert settings.grpc_port == 81
