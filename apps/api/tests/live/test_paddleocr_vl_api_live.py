from __future__ import annotations

import os
from pathlib import Path

import pytest

from mistake_notebook_api.domain.ocr import OCRInput
from mistake_notebook_api.infrastructure.ocr.paddle_vl_api import PaddleOCRVLAPIProvider


@pytest.mark.live
def test_real_paddleocr_vl_recognizes_an_authorized_image() -> None:
    if os.environ.get("RUN_LIVE_PADDLEOCR") != "1":
        pytest.skip("set RUN_LIVE_PADDLEOCR=1 to consume a real PaddleOCR page")
    token = os.environ.get("PADDLEOCR_ACCESS_TOKEN", "").strip()
    image_path_value = os.environ.get("PADDLEOCR_LIVE_IMAGE", "").strip()
    if not token or not image_path_value:
        pytest.skip("PADDLEOCR_ACCESS_TOKEN and PADDLEOCR_LIVE_IMAGE are required")

    image_path = Path(image_path_value).expanduser().resolve()
    if not image_path.is_file():
        pytest.fail("PADDLEOCR_LIVE_IMAGE does not point to a readable file")
    media_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"

    result = PaddleOCRVLAPIProvider(token=token).recognize(
        OCRInput(
            source_asset_id="asset_live",
            problem_region_id="region_live",
            image_bytes=image_path.read_bytes(),
            media_type=media_type,
        )
    )

    assert result.provider == "paddleocr_vl_api"
    assert result.model == "PaddleOCR-VL-1.6"
    assert result.processing_time_ms > 0
    assert result.raw_response
