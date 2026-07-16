from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from importlib import metadata
from io import BytesIO
from time import perf_counter

from PIL import Image, ImageOps

from mistake_notebook_api.domain.enums import OCRBlockType
from mistake_notebook_api.domain.errors import JsonValue, OCRProviderError
from mistake_notebook_api.domain.geometry import BoundingBox
from mistake_notebook_api.domain.ocr import (
    OCRBlock,
    OCRInput,
    OCRResult,
    ProviderHealth,
)


def to_json_value(value: object) -> JsonValue:
    if isinstance(value, float) and not math.isfinite(value):
        raise OCRProviderError("invalid_response")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_json_value(item) for item in value]
    to_list = getattr(value, "tolist", None)
    if callable(to_list):
        return to_json_value(to_list())
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if isinstance(scalar, (str, int, float, bool)) or scalar is None:
            return scalar
    raise OCRProviderError("invalid_response")


def _result_json(result: object) -> dict[str, JsonValue]:
    json_value = getattr(result, "json", None)
    if callable(json_value):
        json_value = json_value()
    if json_value is None:
        to_dict = getattr(result, "to_dict", None)
        json_value = to_dict() if callable(to_dict) else None
    if json_value is None and isinstance(result, Mapping):
        json_value = result
    converted = to_json_value(json_value)
    if not isinstance(converted, dict):
        raise OCRProviderError("invalid_response")
    return converted


def _normalization_payload(result_json: dict[str, JsonValue]) -> dict[str, JsonValue]:
    nested = result_json.get("res")
    return nested if isinstance(nested, dict) else result_json


def _number(value: JsonValue | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _bbox_from_value(value: JsonValue | None) -> BoundingBox | None:
    if not isinstance(value, list) or not value:
        return None
    if len(value) == 4:
        numeric: list[float] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                break
            numeric.append(float(item))
        if len(numeric) == 4:
            left, top, right, bottom = (round(item) for item in numeric)
        else:
            return None
    else:
        points = [item for item in value if isinstance(item, list) and len(item) >= 2]
        if not points:
            return None
        xs = [float(point[0]) for point in points if isinstance(point[0], (int, float))]
        ys = [float(point[1]) for point in points if isinstance(point[1], (int, float))]
        if not xs or not ys:
            return None
        left, top, right, bottom = (
            round(min(xs)),
            round(min(ys)),
            round(max(xs)),
            round(max(ys)),
        )
    return BoundingBox(left, top, max(1, right - left), max(1, bottom - top))


def normalize_paddle_results(
    results: Iterable[object], *, provider_version: str | None, model_name: str
) -> OCRResult:
    started = perf_counter()
    raw_results = [_result_json(result) for result in results]
    payloads = [_normalization_payload(result) for result in raw_results]
    blocks: list[OCRBlock] = []
    scores: list[float] = []

    for payload in payloads:
        texts = payload.get("rec_texts", [])
        raw_scores = payload.get("rec_scores", [])
        boxes = payload.get("rec_boxes", payload.get("rec_polys", []))
        if not isinstance(texts, list):
            raise OCRProviderError("invalid_response")
        score_list = raw_scores if isinstance(raw_scores, list) else []
        box_list = boxes if isinstance(boxes, list) else []
        for local_index, text_value in enumerate(texts):
            if not isinstance(text_value, str):
                raise OCRProviderError("invalid_response")
            index = len(blocks)
            confidence = _number(score_list[local_index] if local_index < len(score_list) else None)
            if confidence is not None:
                scores.append(confidence)
            blocks.append(
                OCRBlock(
                    type=OCRBlockType.TEXT,
                    text=text_value,
                    bbox=_bbox_from_value(
                        box_list[local_index] if local_index < len(box_list) else None
                    ),
                    confidence=confidence,
                    reading_order=index,
                    metadata={},
                )
            )

    text = "\n".join(block.text for block in blocks if block.text.strip())
    warnings = [] if text else ["ocr_empty_text"]
    return OCRResult(
        provider="paddleocr",
        model=model_name,
        provider_version=provider_version,
        text=text,
        confidence=sum(scores) / len(scores) if scores else None,
        blocks=blocks,
        raw_response=to_json_value({"results": raw_results}),
        warnings=warnings,
        processing_time_ms=max(1, round((perf_counter() - started) * 1000)),
    )


class PaddleOCRProvider:
    name = "paddleocr"

    def __init__(self, *, language: str, model_name: str) -> None:
        self.language = language
        self.model_name = model_name
        self._engine: object | None = None

    def _get_engine(self) -> object:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR

            self._engine = PaddleOCR(
                lang=self.language,
                text_recognition_model_name=self.model_name,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                # Paddle 3.3 on Windows can route the default detector through
                # oneDNN and fail on ArrayAttribute conversion before inference.
                # The plain CPU executor is slower but deterministic and portable.
                enable_mkldnn=False,
            )
            return self._engine
        except (ImportError, ModuleNotFoundError):
            raise OCRProviderError("configuration_error") from None
        except (AssertionError, KeyError, TypeError, ValueError):
            raise OCRProviderError("configuration_error") from None
        except Exception:
            raise OCRProviderError("unavailable") from None

    def recognize(self, input: OCRInput) -> OCRResult:
        started = perf_counter()
        try:
            import numpy as np

            with Image.open(BytesIO(input.image_bytes)) as image:
                oriented = ImageOps.exif_transpose(image).convert("RGB")
                image_array = np.asarray(oriented)
            engine = self._get_engine()
            predict = getattr(engine, "predict", None)
            if not callable(predict):
                raise OCRProviderError("invalid_response")
            results = predict(image_array)
            version = metadata.version("paddleocr")
            normalized = normalize_paddle_results(
                results, provider_version=version, model_name=self.model_name
            )
            return replace(
                normalized,
                processing_time_ms=max(1, round((perf_counter() - started) * 1000)),
            )
        except OCRProviderError:
            raise
        except TimeoutError:
            raise OCRProviderError("timeout") from None
        except (ImportError, ModuleNotFoundError):
            raise OCRProviderError("configuration_error") from None
        except Exception:
            raise OCRProviderError("unavailable") from None

    def health_check(self) -> ProviderHealth:
        try:
            self._get_engine()
        except OCRProviderError as error:
            return ProviderHealth(False, self.name, error.category)
        return ProviderHealth(True, self.name, "ready")
