"""The served OpenAPI document must equal the frozen golden exactly."""

import json
from pathlib import Path

GOLDEN = Path(__file__).resolve().parents[4] / "contracts" / "openapi" / "ordering.swagger.json"
PACKAGED = Path(__file__).resolve().parents[1] / "ordering_api" / "contracts" / "ordering.swagger.json"


def test_packaged_document_equals_frozen_golden():
    assert json.loads(PACKAGED.read_text(encoding="utf-8-sig")) == json.loads(
        GOLDEN.read_text(encoding="utf-8-sig")
    )


async def test_served_swagger_matches_golden(client):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8-sig"))
    response = await client.get("/swagger/v1/swagger.json")
    assert response.status_code == 200
    assert response.json() == golden
