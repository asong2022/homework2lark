from __future__ import annotations

from mistake_notebook_api.domain.enums import ReviewStatus


def status_after_ocr(current: ReviewStatus, extracted_text: str) -> ReviewStatus:
    if current is ReviewStatus.REVIEWED:
        return current
    if extracted_text.strip():
        return ReviewStatus.NEEDS_REVIEW
    return ReviewStatus.OCR_COMPLETED


def is_future_reuse_eligible(status: ReviewStatus, current_revision_id: str | None) -> bool:
    return status is ReviewStatus.REVIEWED and current_revision_id is not None
