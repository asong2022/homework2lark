from __future__ import annotations

from dataclasses import dataclass

from mistake_notebook_api.domain.enums import OCRBlockType
from mistake_notebook_api.domain.geometry import BoundingBox
from mistake_notebook_api.domain.ocr import (
    OCRBlock,
    OCRInput,
    OCRResult,
    ProviderHealth,
)


@dataclass(slots=True)
class StubOCRProvider:
    text: str = "小明有24本书，平均放在6层书架上，每层放几本？"
    name: str = "test_stub"
    model_name: str = "deterministic-test-only"

    def recognize(self, input: OCRInput) -> OCRResult:
        return OCRResult(
            provider=self.name,
            model=self.model_name,
            provider_version="test-only",
            text=self.text,
            confidence=0.99,
            blocks=[
                OCRBlock(
                    type=OCRBlockType.TEXT,
                    text=self.text,
                    bbox=BoundingBox(x=0, y=0, width=1, height=1),
                    confidence=0.99,
                    reading_order=0,
                    metadata={"fixture": "test-only"},
                )
            ],
            raw_response={
                "fixture": "test-only",
                "sourceAssetId": input.source_asset_id,
                "problemRegionId": input.problem_region_id,
            },
            warnings=[] if self.text else ["ocr_empty_text"],
            processing_time_ms=1,
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(True, self.name, "ready")
