from __future__ import annotations

from time import perf_counter

from mistake_notebook_api.domain.enums import OCRBlockType
from mistake_notebook_api.domain.geometry import BoundingBox
from mistake_notebook_api.domain.ocr import (
    OCRBlock,
    OCRInput,
    OCRResult,
    ProviderHealth,
)


class FakeOCRProvider:
    name = "fake"
    model_name = "deterministic-v1"

    def recognize(self, input: OCRInput) -> OCRResult:
        started = perf_counter()
        text = "小明有24本书，平均放在6层书架上，每层放几本？"
        return OCRResult(
            provider=self.name,
            model=self.model_name,
            provider_version="1.0",
            text=text,
            confidence=0.99,
            blocks=[
                OCRBlock(
                    type=OCRBlockType.TEXT,
                    text=text,
                    bbox=BoundingBox(x=0, y=0, width=1, height=1),
                    confidence=0.99,
                    reading_order=0,
                    metadata={"fixture": "phase-one"},
                )
            ],
            raw_response={
                "engine": "fake",
                "sourceAssetId": input.source_asset_id,
                "problemRegionId": input.problem_region_id,
                "lineCount": 1,
            },
            warnings=[],
            processing_time_ms=max(1, round((perf_counter() - started) * 1000)),
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(True, self.name, "ready")
