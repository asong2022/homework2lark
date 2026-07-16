from __future__ import annotations

import json
from pathlib import Path

from mistake_notebook_api.main import create_app


def test_committed_openapi_matches_application() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    committed = json.loads(
        (repository_root / "packages" / "contracts" / "openapi.json").read_text(encoding="utf-8")
    )
    generated = create_app().openapi()
    assert committed == generated

    schemas = generated["components"]["schemas"]
    assert "ErrorEnvelope" in schemas
    assert "HTTPValidationError" not in schemas

    paths = generated["paths"]
    assert "/api/v1/assets/{asset_id}/problems" in paths
    upload_responses = paths["/api/v1/assets"]["post"]["responses"]
    assert {"201", "400", "413", "415", "422", "500"} <= set(upload_responses)
    assert upload_responses["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }

    ocr_responses = paths["/api/v1/regions/{region_id}/ocr-runs"]["post"]["responses"]
    assert {"201", "422", "500", "502", "503", "504"} <= set(ocr_responses)
