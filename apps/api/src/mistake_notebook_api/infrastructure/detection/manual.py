from __future__ import annotations

from mistake_notebook_api.domain.detection import (
    DetectionProviderHealth,
    RegionDetectionInput,
    RegionDetectionResult,
)
from mistake_notebook_api.domain.errors import RegionDetectionProviderError


class ManualOnlyRegionDetectionProvider:
    """Explicitly disables automatic framing without fabricating candidates."""

    name = "manual"
    model_name = "teacher-manual"

    def detect(self, input: RegionDetectionInput) -> RegionDetectionResult:
        del input
        raise RegionDetectionProviderError("configuration_error")

    def health_check(self) -> DetectionProviderHealth:
        return DetectionProviderHealth(False, self.name, "仅支持教师手动框题")
