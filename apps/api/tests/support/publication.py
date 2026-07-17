from __future__ import annotations

from mistake_notebook_api.domain.publication import (
    ProblemPublicationRequest,
    ProblemPublicationResult,
)


class StubProblemPublisher:
    @property
    def name(self) -> str:
        return "test_stub"

    def publish(self, request: ProblemPublicationRequest) -> ProblemPublicationResult:
        return ProblemPublicationResult(
            base_name="test-math-problems",
            pages_table_id="tbl_test_pages",
            questions_table_id="tbl_test_questions",
            page_record_id=f"rec_{request.source_asset_id}",
            question_record_id=f"rec_{request.problem_id}",
        )
