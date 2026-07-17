from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from types import ModuleType

import pytest
from tests.conftest import image_bytes

from mistake_notebook_api.domain.errors import OCRProviderError
from mistake_notebook_api.domain.ocr import OCRInput
from mistake_notebook_api.infrastructure.ocr import paddle as paddle_module
from mistake_notebook_api.infrastructure.ocr.paddle import (
    PaddleOCRProvider,
    normalize_paddle_results,
    to_json_value,
)


@dataclass
class ArrayLike:
    value: object

    def tolist(self) -> object:
        return self.value


class PaddleResultLike(dict[str, object]):
    def json(self) -> dict[str, object]:
        return {
            "res": {
                "rec_texts": ["完整题目"],
                "rec_scores": [0.9],
                "rec_boxes": [[1, 2, 50, 20]],
            }
        }


def test_paddle_result_is_normalized_and_json_safe() -> None:
    result = normalize_paddle_results(
        [
            {
                "res": {
                    "rec_texts": ["24÷6=4"],
                    "rec_scores": ArrayLike([0.95]),
                    "rec_boxes": ArrayLike([[1, 2, 101, 32]]),
                },
                "trace_id": "trace-preserved",
            }
        ],
        provider_version="3.3.0",
        model_name="PP-OCRv5_server_rec",
    )
    assert result.text == "24÷6=4"
    assert result.confidence == pytest.approx(0.95)
    assert result.blocks[0].bbox is not None
    assert result.blocks[0].bbox.width == 100
    assert result.raw_response == {
        "results": [
            {
                "res": {
                    "rec_texts": ["24÷6=4"],
                    "rec_scores": [0.95],
                    "rec_boxes": [[1, 2, 101, 32]],
                },
                "trace_id": "trace-preserved",
            }
        ]
    }


class SlowPaddleEngine:
    def predict(self, _: object) -> list[dict[str, object]]:
        time.sleep(0.03)
        return [
            {
                "res": {
                    "rec_texts": ["24÷6=4"],
                    "rec_scores": [0.95],
                    "rec_boxes": [[1, 2, 101, 32]],
                }
            }
        ]


class FakeNumpyModule(ModuleType):
    @staticmethod
    def asarray(value: object) -> object:
        return value


def test_paddle_processing_time_includes_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_numpy = FakeNumpyModule("numpy")
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy)
    monkeypatch.setattr(paddle_module.metadata, "version", lambda _: "3.test")

    provider = PaddleOCRProvider(language="ch", model_name="test-model")
    provider._engine = SlowPaddleEngine()
    result = provider.recognize(
        OCRInput(
            source_asset_id="asset_1",
            problem_region_id="region_1",
            image_bytes=image_bytes(),
        )
    )

    assert result.processing_time_ms >= 25


def test_non_finite_provider_value_is_rejected() -> None:
    with pytest.raises(OCRProviderError):
        to_json_value(float("nan"))


def test_paddle_prefers_vendor_json_over_mapping_visualization_objects() -> None:
    result = PaddleResultLike(vis_fonts=[object()])

    normalized = normalize_paddle_results(
        [result], provider_version="3.7.0", model_name="test-model"
    )

    assert normalized.text == "完整题目"
    assert normalized.raw_response == {"results": [result.json()]}


def test_invalid_paddle_model_configuration_is_not_reported_as_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("paddleocr")

    def invalid_model(**_: object) -> None:
        raise ValueError("unknown recognition model")

    module.__dict__["PaddleOCR"] = invalid_model
    monkeypatch.setitem(sys.modules, "paddleocr", module)
    provider = PaddleOCRProvider(language="ch", model_name="invalid-model")

    health = provider.health_check()
    assert health.available is False
    assert health.message == "configuration_error"


def test_paddle_disables_windows_onednn_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("paddleocr")
    captured: dict[str, object] = {}

    def fake_paddle(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    module.__dict__["PaddleOCR"] = fake_paddle
    monkeypatch.setitem(sys.modules, "paddleocr", module)

    PaddleOCRProvider(language="ch", model_name="test-model")._get_engine()

    assert captured["enable_mkldnn"] is False
