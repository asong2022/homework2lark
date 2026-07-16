from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT / "src"))

from mistake_notebook_api.application.images import inspect_image  # noqa: E402
from mistake_notebook_api.config import Settings  # noqa: E402
from mistake_notebook_api.domain.detection import RegionDetectionInput  # noqa: E402
from mistake_notebook_api.domain.errors import RegionDetectionProviderError  # noqa: E402
from mistake_notebook_api.infrastructure.yescan.client import YescanApiClient  # noqa: E402
from mistake_notebook_api.infrastructure.yescan.question_detection import (  # noqa: E402
    YescanQuestionDetectionProvider,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a summary-only Yescan question detection")
    parser.add_argument("image", type=Path, help="Explicit JPG/JPEG/PNG image path")
    args = parser.parse_args()

    settings = Settings()
    image_bytes = args.image.read_bytes()
    metadata = inspect_image(image_bytes, max_pixels=settings.max_image_pixels)
    if settings.yescan_api_key is None or settings.yescan_api_key_id is None:
        print(json.dumps({"status": "configuration_error"}, ensure_ascii=False))
        return 2

    provider = YescanQuestionDetectionProvider(
        YescanApiClient(
            client_id=settings.yescan_api_key_id,
            client_secret=settings.yescan_api_key.get_secret_value(),
            endpoint=settings.yescan_api_base_url,
            timeout_seconds=settings.yescan_timeout_seconds,
        )
    )
    try:
        result = provider.detect(
            RegionDetectionInput(
                source_asset_id="benchmark",
                image_bytes=image_bytes,
                media_type=metadata.media_type,
                width=metadata.width,
                height=metadata.height,
            )
        )
    except RegionDetectionProviderError as error:
        print(json.dumps({"status": error.category}, ensure_ascii=False))
        return 1

    summary = {
        "status": "succeeded",
        "provider": result.provider,
        "model": result.model,
        "candidateCount": len(result.candidates),
        "processingTimeMs": result.processing_time_ms,
        "warnings": result.warnings,
        "candidates": [
            {
                "providerCandidateId": candidate.provider_candidate_id,
                "readingOrder": candidate.reading_order,
                "bbox": {
                    "x": candidate.bbox.x,
                    "y": candidate.bbox.y,
                    "width": candidate.bbox.width,
                    "height": candidate.bbox.height,
                },
                "confidence": candidate.confidence,
                "metadata": candidate.metadata,
            }
            for candidate in result.candidates
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
