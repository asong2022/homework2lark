from __future__ import annotations

import pytest

from mistake_notebook_api.api.runtime import (
    build_problem_publisher,
    build_region_detection_provider,
)
from mistake_notebook_api.config import Settings
from mistake_notebook_api.domain.errors import AppError
from mistake_notebook_api.infrastructure.detection.manual import (
    ManualOnlyRegionDetectionProvider,
)
from mistake_notebook_api.infrastructure.publication.lark_cli import (
    LarkCliProblemPublisher,
)


def test_production_defaults_are_manual_framing_and_real_lark_publication() -> None:
    assert Settings.model_fields["region_detection_provider"].default == "manual"
    assert Settings.model_fields["problem_publisher"].default == "lark_cli"
    settings = Settings(region_detection_provider="manual", problem_publisher="lark_cli")

    assert isinstance(build_region_detection_provider(settings), ManualOnlyRegionDetectionProvider)
    assert isinstance(build_problem_publisher(settings), LarkCliProblemPublisher)


@pytest.mark.parametrize(
    ("field", "builder", "expected_code"),
    [
        (
            "region_detection_provider",
            build_region_detection_provider,
            "region_detection_provider_configuration_error",
        ),
        (
            "problem_publisher",
            build_problem_publisher,
            "lark_publisher_configuration_error",
        ),
    ],
)
def test_test_doubles_cannot_be_selected_from_production_configuration(
    field: str, builder: object, expected_code: str
) -> None:
    settings = Settings(**{field: "fake"})
    assert callable(builder)

    with pytest.raises(AppError) as raised:
        builder(settings)

    assert raised.value.code == expected_code
