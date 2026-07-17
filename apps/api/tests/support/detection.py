from __future__ import annotations

from time import perf_counter

from mistake_notebook_api.domain.detection import (
    DetectionProviderHealth,
    RegionCandidate,
    RegionDetectionInput,
    RegionDetectionResult,
)
from mistake_notebook_api.domain.geometry import BoundingBox


class StubProblemRegionDetectionProvider:
    name = "test_stub"
    model_name = "deterministic-test-only"

    def detect(self, input: RegionDetectionInput) -> RegionDetectionResult:
        started = perf_counter()
        ratios = (
            (0.08, 0.14, 0.58, 0.18),
            (0.68, 0.14, 0.24, 0.18),
            (0.08, 0.46, 0.84, 0.18),
        )
        candidates = [
            RegionCandidate(
                provider_candidate_id=f"test-{index + 1}",
                bbox=BoundingBox(
                    x=round(x * input.width),
                    y=round(y * input.height),
                    width=max(1, round(width * input.width)),
                    height=max(1, round(height * input.height)),
                ),
                confidence=0.99,
                reading_order=index,
                metadata={"fixture": "test-only"},
            )
            for index, (x, y, width, height) in enumerate(ratios)
        ]
        return RegionDetectionResult(
            provider=self.name,
            model=self.model_name,
            provider_version="test-only",
            candidates=candidates,
            raw_response={
                "fixture": "test-only",
                "candidateCount": len(candidates),
            },
            warnings=[],
            processing_time_ms=max(1, round((perf_counter() - started) * 1000)),
        )

    def health_check(self) -> DetectionProviderHealth:
        return DetectionProviderHealth(True, self.name, "ready")
