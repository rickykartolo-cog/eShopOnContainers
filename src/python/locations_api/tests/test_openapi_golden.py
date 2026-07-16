"""The served OpenAPI document must equal the frozen golden exactly."""

import json
from pathlib import Path

from locations_api.openapi_document import build_document

GOLDEN = Path(__file__).resolve().parents[4] / "contracts" / "openapi" / "locations.swagger.json"


def test_document_matches_golden():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8-sig"))
    assert build_document("http://localhost:5105") == golden


async def test_served_swagger_matches_golden(client):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8-sig"))
    response = await client.get("/swagger/v1/swagger.json")
    assert response.status_code == 200
    assert response.json() == golden
