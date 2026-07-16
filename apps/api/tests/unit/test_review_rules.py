from __future__ import annotations

import pytest

from mistake_notebook_api.domain.enums import ReviewStatus
from mistake_notebook_api.domain.review_rules import (
    is_future_reuse_eligible,
    status_after_ocr,
)


@pytest.mark.parametrize(
    ("status", "text", "expected"),
    [
        (ReviewStatus.DRAFT, "题目", ReviewStatus.NEEDS_REVIEW),
        (ReviewStatus.DRAFT, "  ", ReviewStatus.OCR_COMPLETED),
        (ReviewStatus.REVIEWED, "新 OCR", ReviewStatus.REVIEWED),
    ],
)
def test_status_after_ocr(status: ReviewStatus, text: str, expected: ReviewStatus) -> None:
    assert status_after_ocr(status, text) is expected


def test_reuse_eligibility_requires_review_and_revision() -> None:
    assert is_future_reuse_eligible(ReviewStatus.REVIEWED, "revision_1")
    assert not is_future_reuse_eligible(ReviewStatus.REVIEWED, None)
    assert not is_future_reuse_eligible(ReviewStatus.NEEDS_REVIEW, "revision_1")
