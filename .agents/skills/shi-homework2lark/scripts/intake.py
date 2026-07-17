#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
DEFAULT_WEB_URL = "http://localhost:3000"
SESSION_VERSION = 1
IMAGE_SUFFIXES = frozenset((".jpg", ".jpeg", ".png"))
DOCUMENT_SUFFIXES = frozenset((".pdf", ".doc", ".docx"))
PAGE_METADATA_FIELDS = frozenset(
    ("页面名称", "时间", "年级", "页码", "单元", "课题名", "错题来源", "页面主知识点")
)
PAGE_SOURCE_OPTIONS = frozenset(("教材", "作业本", "试卷", "其他"))
GRADE_OPTIONS = frozenset(("一年级", "二年级", "三年级", "四年级", "五年级", "六年级"))
QUESTION_METADATA_FIELDS = frozenset(
    (
        "题号",
        "题目名称",
        "分区标题",
        "题型",
        "核心素养",
        "对应知识点",
        "图表说明",
        "标准答案",
        "答案备注",
        "设计意图",
    )
)
QUESTION_TYPE_OPTIONS = frozenset(
    (
        "选择题",
        "填空题",
        "判断题",
        "计算题",
        "解答题",
        "操作题",
        "应用题",
        "开放题",
        "其他",
    )
)
CORE_LITERACY_OPTIONS = frozenset(
    (
        "数感",
        "量感",
        "符号意识",
        "运算能力",
        "几何直观",
        "空间观念",
        "推理意识",
        "数据意识",
        "模型意识",
        "应用意识",
        "创新意识",
    )
)


class SkillError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.request_id = request_id


class Gateway(Protocol):
    def health(self) -> dict[str, JSONValue]: ...

    def upload(self, path: Path) -> dict[str, JSONValue]: ...

    def detect(self, asset_id: str) -> dict[str, JSONValue]: ...

    def create_regions(
        self, asset_id: str, regions: list[dict[str, JSONValue]]
    ) -> dict[str, JSONValue]: ...

    def get_problem(self, problem_id: str) -> dict[str, JSONValue]: ...

    def run_ocr(self, region_id: str) -> dict[str, JSONValue]: ...

    def create_revision(
        self, region_id: str, payload: dict[str, JSONValue]
    ) -> dict[str, JSONValue]: ...

    def publish(self, problem_id: str) -> dict[str, JSONValue]: ...

    def download(self, path: str) -> bytes: ...


class HttpGateway:
    def __init__(self, api_url: str, *, timeout_seconds: int = 120) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, JSONValue]:
        return self._json("GET", "/health")

    def upload(self, path: Path) -> dict[str, JSONValue]:
        boundary = f"----shi-homework2lark-{uuid.uuid4().hex}"
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = _multipart_body(boundary, path.name, media_type, path.read_bytes())
        return self._json(
            "POST",
            "/assets",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def detect(self, asset_id: str) -> dict[str, JSONValue]:
        return self._json("POST", f"/assets/{urllib.parse.quote(asset_id)}/detection-runs")

    def create_regions(
        self, asset_id: str, regions: list[dict[str, JSONValue]]
    ) -> dict[str, JSONValue]:
        return self._json(
            "POST",
            f"/assets/{urllib.parse.quote(asset_id)}/regions/batch",
            payload={"coordinateSystem": "normalized_top_left", "regions": regions},
        )

    def get_problem(self, problem_id: str) -> dict[str, JSONValue]:
        return self._json("GET", f"/problems/{urllib.parse.quote(problem_id)}")

    def run_ocr(self, region_id: str) -> dict[str, JSONValue]:
        return self._json("POST", f"/regions/{urllib.parse.quote(region_id)}/ocr-runs")

    def create_revision(
        self, region_id: str, payload: dict[str, JSONValue]
    ) -> dict[str, JSONValue]:
        return self._json(
            "POST",
            f"/regions/{urllib.parse.quote(region_id)}/revisions",
            payload=payload,
        )

    def publish(self, problem_id: str) -> dict[str, JSONValue]:
        return self._json("POST", f"/problems/{urllib.parse.quote(problem_id)}/publications/lark")

    def download(self, path: str) -> bytes:
        request = urllib.request.Request(self._url(path), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise _http_error(exc) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SkillError(
                "api_unavailable",
                "本地错题服务不可用，请先启动项目后重试。",
                retryable=True,
            ) from None

    def _json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, JSONValue] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, JSONValue]:
        request_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._url(path), data=data, headers=request_headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                decoded: JSONValue = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise _http_error(exc) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SkillError(
                "api_unavailable",
                "本地错题服务不可用，请先启动项目后重试。",
                retryable=True,
            ) from None
        except (json.JSONDecodeError, UnicodeError):
            raise SkillError("api_invalid_response", "本地错题服务返回了无法识别的数据。") from None
        return _object(decoded, "API 响应")

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        normalized_path = f"/{path.lstrip('/')}"
        api_parts = urllib.parse.urlsplit(self.api_url)
        api_path = api_parts.path.rstrip("/")
        if api_path and (normalized_path == api_path or normalized_path.startswith(f"{api_path}/")):
            return urllib.parse.urlunsplit(
                (api_parts.scheme, api_parts.netloc, normalized_path, "", "")
            )
        return f"{self.api_url}/{path.lstrip('/')}"


class IntakeService:
    def __init__(
        self,
        gateway: Gateway,
        *,
        web_url: str = DEFAULT_WEB_URL,
    ) -> None:
        self.gateway = gateway
        self.web_url = web_url.rstrip("/")

    def health(self) -> dict[str, JSONValue]:
        health = self.gateway.health()
        ocr_provider = _string(health.get("ocrProvider"), "ocrProvider")
        detection_provider = _string(
            health.get("regionDetectionProvider"), "regionDetectionProvider"
        )
        return {
            "status": _string(health.get("status"), "status"),
            "database": _string(health.get("database"), "database"),
            "ocrProvider": ocr_provider,
            "regionDetectionProvider": detection_provider,
            "realChatDetectionReady": detection_provider != "fake",
        }

    def start(self, path: Path, mode: str) -> dict[str, JSONValue]:
        self._validate_image(path)
        health = self.health()
        if mode == "chat":
            self._require_real_detection_provider(
                _string(health["regionDetectionProvider"], "regionDetectionProvider")
            )
        source = self.gateway.upload(path)
        asset_id = _string(source.get("assetId"), "assetId")
        source_manifest: dict[str, JSONValue] = {
            "assetId": asset_id,
            "fileName": _string(source.get("fileName"), "fileName"),
            "mediaType": _string(source.get("mediaType"), "mediaType"),
            "width": _positive_int(source.get("width"), "width"),
            "height": _positive_int(source.get("height"), "height"),
            "contentUrl": _string(source.get("contentUrl"), "contentUrl"),
        }
        manifest: dict[str, JSONValue] = {
            "schemaVersion": SESSION_VERSION,
            "mode": mode,
            "source": source_manifest,
            "webUrl": f"{self.web_url}/intake/{urllib.parse.quote(asset_id)}",
            "detection": None,
            "problems": [],
        }
        if mode == "chat":
            detection = self.gateway.detect(asset_id)
            provider = _string(detection.get("provider"), "provider")
            self._require_real_detection_provider(provider)
            raw_candidates = _list(detection.get("candidates"), "candidates")
            candidates = [self._candidate(item) for item in raw_candidates]
            manifest["detection"] = {
                "runId": _string(detection.get("runId"), "runId"),
                "provider": provider,
                "model": _optional_string(detection.get("model")),
                "warnings": _string_list(detection.get("warnings"), "warnings"),
                "candidates": candidates,
            }
        elif mode == "single":
            batch = self.gateway.create_regions(
                asset_id,
                [
                    {
                        "selectionSource": "manual",
                        "detectionCandidateIds": [],
                        "bbox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                    }
                ],
            )
            manifest["problems"] = self._problems_from_batch(batch)
        return manifest

    def select(
        self, session: dict[str, JSONValue], candidate_ids: Sequence[str]
    ) -> dict[str, JSONValue]:
        _validate_session(session, required_mode="chat")
        if not candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
            raise SkillError("invalid_selection", "请提供一个或多个不重复的候选 ID。")
        detection = _object(session.get("detection"), "detection")
        available = {
            _string(candidate.get("candidateId"), "candidateId"): candidate
            for candidate in (
                _object(item, "candidate")
                for item in _list(detection.get("candidates"), "candidates")
            )
        }
        missing = [candidate_id for candidate_id in candidate_ids if candidate_id not in available]
        if missing:
            raise SkillError("invalid_selection", "选择中包含当前会话不存在的候选 ID。")
        regions: list[dict[str, JSONValue]] = []
        for candidate_id in candidate_ids:
            candidate = available[candidate_id]
            regions.append(
                {
                    "selectionSource": "detected",
                    "detectionCandidateIds": [candidate_id],
                    "bbox": _object(candidate.get("normalizedBbox"), "normalizedBbox"),
                }
            )
        source = _object(session.get("source"), "source")
        batch = self.gateway.create_regions(_string(source.get("assetId"), "assetId"), regions)
        return {
            "schemaVersion": SESSION_VERSION,
            "mode": "chat-selection",
            "source": source,
            "detectionRunId": _string(detection.get("runId"), "runId"),
            "selectedCandidateIds": list(candidate_ids),
            "problems": self._problems_from_batch(batch),
        }

    def ocr(self, problem_id: str) -> dict[str, JSONValue]:
        record = self.gateway.get_problem(problem_id)
        region = _object(record.get("region"), "region")
        run = self.gateway.run_ocr(_string(region.get("regionId"), "regionId"))
        provider = _string(run.get("provider"), "provider")
        return {
            "problemId": problem_id,
            "runId": _string(run.get("runId"), "runId"),
            "provider": provider,
            "model": _optional_string(run.get("model")),
            "status": _string(run.get("status"), "status"),
            "text": _optional_string(run.get("text")),
            "confidence": run.get("confidence"),
            "warnings": _string_list(run.get("warnings"), "warnings"),
        }

    def get(self, problem_id: str) -> dict[str, JSONValue]:
        return _project_problem(self.gateway.get_problem(problem_id))

    def save_revision(self, problem_id: str, payload: dict[str, JSONValue]) -> dict[str, JSONValue]:
        allowed = {
            "correctedText",
            "correctionNote",
            "basedOnOcrRunId",
            "questionNumber",
        }
        if set(payload) - allowed:
            raise SkillError("invalid_payload", "修订输入包含未支持的字段。")
        record = self.gateway.get_problem(problem_id)
        region = _object(record.get("region"), "region")
        based_on = _optional_string(payload.get("basedOnOcrRunId"))
        if based_on is None:
            latest = _object(record.get("latestOcrRun"), "latestOcrRun")
            based_on = _string(latest.get("runId"), "runId")
        corrected_text = _nonempty_text(payload.get("correctedText"), "correctedText", 50_000)
        question_number = _question_number(payload.get("questionNumber"))
        if question_number is not None:
            corrected_text = _strip_matching_question_number(corrected_text, question_number)
        note = payload.get("correctionNote")
        if note is not None and (not isinstance(note, str) or len(note) > 2_000):
            raise SkillError("invalid_payload", "correctionNote 必须是不超过 2000 字的文本。")
        revision = self.gateway.create_revision(
            _string(region.get("regionId"), "regionId"),
            {
                "basedOnOcrRunId": based_on,
                "correctedText": corrected_text,
                "correctionNote": note,
            },
        )
        return {
            "problemId": problem_id,
            "revisionId": _string(revision.get("revisionId"), "revisionId"),
            "revisionNumber": _positive_int(revision.get("revisionNumber"), "revisionNumber"),
            "correctedText": _string(revision.get("correctedText"), "correctedText"),
            "correctionNote": _optional_string(revision.get("correctionNote")),
        }

    def publish(self, problem_id: str) -> dict[str, JSONValue]:
        publication = self.gateway.publish(problem_id)
        return {
            "problemId": problem_id,
            "publisher": _string(publication.get("publisher"), "publisher"),
            "status": _string(publication.get("status"), "status"),
            "baseName": _string(publication.get("baseName"), "baseName"),
            "retryable": publication.get("retryable") is True,
            "updatedAt": publication.get("updatedAt"),
        }

    def download_evidence(self, problem_id: str, output_dir: Path) -> dict[str, JSONValue]:
        record = self.gateway.get_problem(problem_id)
        source = _object(record.get("source"), "source")
        region = _object(record.get("region"), "region")
        source_name = Path(_string(source.get("fileName"), "fileName").replace("\\", "/")).name
        if not source_name:
            source_name = "source.png"
        crop_name = f"{problem_id}-crop.png"
        (output_dir / source_name).write_bytes(
            self.gateway.download(_string(source.get("contentUrl"), "contentUrl"))
        )
        (output_dir / crop_name).write_bytes(
            self.gateway.download(_string(region.get("cropContentUrl"), "cropContentUrl"))
        )
        return {
            "problemId": problem_id,
            "outputDir": output_dir.relative_to(Path.cwd().resolve()).as_posix(),
            "files": [source_name, crop_name],
        }

    @staticmethod
    def _require_real_detection_provider(provider: str) -> None:
        if provider == "fake":
            raise SkillError(
                "fake_provider_disabled",
                "对话候选检测当前配置为测试 Provider；请启用真实检测 Provider 后重试。",
            )

    @staticmethod
    def _validate_image(path: Path) -> None:
        if not path.is_file():
            raise SkillError("input_unreadable", "找不到要收集的作业图片。")
        if path.suffix.lower() in DOCUMENT_SUFFIXES:
            raise SkillError(
                "source_requires_page_images",
                "图片录入 CLI 不直接接收 PDF/Word；请由 shi-homework2lark "
                "使用 MinerU 和文档渲染先生成逐页图片。",
            )
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            raise SkillError("unsupported_media_type", "当前只支持 JPG、JPEG 或 PNG 图片。")

    @staticmethod
    def _candidate(value: JSONValue) -> dict[str, JSONValue]:
        item = _object(value, "candidate")
        return {
            "candidateId": _string(item.get("detectionCandidateId"), "detectionCandidateId"),
            "providerCandidateId": _string(item.get("providerCandidateId"), "providerCandidateId"),
            "bbox": _object(item.get("bbox"), "bbox"),
            "normalizedBbox": _object(item.get("normalizedBbox"), "normalizedBbox"),
            "confidence": item.get("confidence"),
            "readingOrder": item.get("readingOrder"),
        }

    @staticmethod
    def _problems_from_batch(batch: dict[str, JSONValue]) -> list[dict[str, JSONValue]]:
        output: list[dict[str, JSONValue]] = []
        for value in _list(batch.get("items"), "items"):
            item = _object(value, "region")
            output.append(
                {
                    "problemId": _string(item.get("problemId"), "problemId"),
                    "regionId": _string(item.get("regionId"), "regionId"),
                    "cropContentUrl": _string(item.get("cropContentUrl"), "cropContentUrl"),
                    "bbox": _object(item.get("bbox"), "bbox"),
                    "selectionSource": _string(item.get("selectionSource"), "selectionSource"),
                }
            )
        if not output:
            raise SkillError("api_invalid_response", "题目区域保存后没有返回任何题目。")
        return output


def _project_problem(record: dict[str, JSONValue]) -> dict[str, JSONValue]:
    source = _object(record.get("source"), "source")
    region = _object(record.get("region"), "region")
    latest_ocr = record.get("latestOcrRun")
    revision = record.get("humanRevision")
    return {
        "problemId": _string(record.get("problemId"), "problemId"),
        "source": {
            "assetId": _string(source.get("assetId"), "assetId"),
            "fileName": _string(source.get("fileName"), "fileName"),
            "width": source.get("width"),
            "height": source.get("height"),
            "contentUrl": _string(source.get("contentUrl"), "contentUrl"),
        },
        "region": {
            "regionId": _string(region.get("regionId"), "regionId"),
            "bbox": _object(region.get("bbox"), "bbox"),
            "cropContentUrl": _string(region.get("cropContentUrl"), "cropContentUrl"),
        },
        "ocr": _project_ocr(latest_ocr),
        "humanRevision": _project_revision(revision),
    }


def _project_ocr(value: JSONValue) -> JSONValue:
    if value is None:
        return None
    ocr = _object(value, "latestOcrRun")
    return {
        "runId": ocr.get("runId"),
        "provider": ocr.get("provider"),
        "model": ocr.get("model"),
        "status": ocr.get("status"),
        "errorCode": ocr.get("errorCode"),
        "text": ocr.get("text"),
        "confidence": ocr.get("confidence"),
        "warnings": ocr.get("warnings"),
    }


def _project_revision(value: JSONValue) -> JSONValue:
    if value is None:
        return None
    revision = _object(value, "humanRevision")
    return {
        "revisionId": revision.get("revisionId"),
        "revisionNumber": revision.get("revisionNumber"),
        "correctedText": revision.get("correctedText"),
        "correctionNote": revision.get("correctionNote"),
    }


def validate_metadata_payload(value: JSONValue) -> dict[str, JSONValue]:
    payload = _object(value, "元数据建议")
    allowed = {"problemId", "page", "question", "note"}
    if set(payload) - allowed:
        raise SkillError("invalid_payload", "元数据建议包含未支持的顶层字段。")
    problem_id = _nonempty_text(payload.get("problemId"), "problemId", 120)
    if not problem_id.startswith("problem_"):
        raise SkillError("invalid_payload", "problemId 必须是本地稳定题目 ID。")
    page = _metadata_fields(payload.get("page"), PAGE_METADATA_FIELDS, "page")
    question = _metadata_fields(payload.get("question"), QUESTION_METADATA_FIELDS, "question")
    if page.get("错题来源") not in PAGE_SOURCE_OPTIONS | {None}:
        raise SkillError("invalid_payload", "page.错题来源不是 Base 支持的选项。")
    if page.get("年级") not in GRADE_OPTIONS | {None}:
        raise SkillError("invalid_payload", "page.年级不是 Base 支持的选项。")
    if question.get("题型") not in QUESTION_TYPE_OPTIONS | {None}:
        raise SkillError("invalid_payload", "question.题型不是 Base 支持的选项。")
    core_literacy = question.get("核心素养")
    if core_literacy is not None:
        if not isinstance(core_literacy, list) or not core_literacy:
            raise SkillError("invalid_payload", "question.核心素养必须是非空选项数组。")
        if len(set(core_literacy)) != len(core_literacy) or not set(core_literacy).issubset(
            CORE_LITERACY_OPTIONS
        ):
            raise SkillError("invalid_payload", "question.核心素养包含重复或未知选项。")
    if not page and not question:
        raise SkillError("invalid_payload", "元数据建议至少需要一个页面或题目字段。")
    note = payload.get("note", "")
    if not isinstance(note, str) or len(note) > 2_000:
        raise SkillError("invalid_payload", "note 必须是不超过 2000 字的文本。")
    return {
        "problemId": problem_id,
        "page": page,
        "question": question,
        "note": note.strip(),
    }


def _metadata_fields(value: JSONValue, allowed: frozenset[str], label: str) -> dict[str, JSONValue]:
    if value is None:
        return {}
    fields = _object(value, label)
    if set(fields) - allowed:
        raise SkillError("invalid_payload", f"{label} 包含未允许写入的字段。")
    output: dict[str, JSONValue] = {}
    for name, field_value in fields.items():
        if name == "核心素养":
            if not isinstance(field_value, list):
                raise SkillError("invalid_payload", f"{label}.{name} 必须是选项数组。")
            output[name] = field_value
            continue
        if not isinstance(field_value, str) or not field_value.strip() or len(field_value) > 5_000:
            raise SkillError("invalid_payload", f"{label}.{name} 必须是非空文本。")
        output[name] = field_value.strip()
    return output


def _multipart_body(boundary: str, file_name: str, media_type: str, data: bytes) -> bytes:
    safe_name = Path(file_name.replace("\\", "/")).name.replace('"', "")
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        f"Content-Type: {media_type}\r\n\r\n"
    ).encode()
    return header + data + f"\r\n--{boundary}--\r\n".encode("ascii")


def _http_error(exc: urllib.error.HTTPError) -> SkillError:
    try:
        decoded: JSONValue = json.loads(exc.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError):
        decoded = None
    if isinstance(decoded, dict) and isinstance(decoded.get("error"), dict):
        error = decoded["error"]
        code = error.get("code") if isinstance(error.get("code"), str) else "api_error"
        message = (
            error.get("message")
            if isinstance(error.get("message"), str)
            else "本地错题服务拒绝了这次操作。"
        )
        return SkillError(
            code,
            message,
            retryable=error.get("retryable") is True,
            request_id=(
                error.get("requestId") if isinstance(error.get("requestId"), str) else None
            ),
        )
    return SkillError("api_error", "本地错题服务拒绝了这次操作。", retryable=exc.code >= 500)


def _validate_session(session: dict[str, JSONValue], *, required_mode: str) -> None:
    if session.get("schemaVersion") != SESSION_VERSION or session.get("mode") != required_mode:
        raise SkillError("invalid_session", "会话文件版本或模式不匹配。")
    _object(session.get("source"), "source")


def _object(value: JSONValue, label: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise SkillError("api_invalid_response", f"{label} 结构无效。")
    return value


def _list(value: JSONValue, label: str) -> list[JSONValue]:
    if not isinstance(value, list):
        raise SkillError("api_invalid_response", f"{label} 必须是数组。")
    return value


def _string(value: JSONValue, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SkillError("api_invalid_response", f"{label} 缺失。")
    return value


def _optional_string(value: JSONValue) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SkillError("api_invalid_response", "可选文本字段类型无效。")
    return value


def _string_list(value: JSONValue, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SkillError("api_invalid_response", f"{label} 必须是文本数组。")
    return [item for item in value if isinstance(item, str)]


def _positive_int(value: JSONValue, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SkillError("api_invalid_response", f"{label} 必须是正整数。")
    return value


def _nonempty_text(value: JSONValue, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise SkillError("invalid_payload", f"{label} 必须是非空文本且不超过 {maximum} 字。")
    return value.strip()


def _question_number(value: JSONValue) -> str | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isascii() and normalized.isdigit() and int(normalized) > 0:
            return normalized
    raise SkillError("invalid_payload", "questionNumber 必须是正整数题号。")


def _strip_matching_question_number(text: str, question_number: str) -> str:
    escaped = re.escape(question_number)
    prefix = re.compile(
        rf"^(?:{escaped}\s*[.．、]\s*|{escaped}\s+|第\s*{escaped}\s*题(?:\s+|[.．、:：]\s*))"
    )
    normalized = prefix.sub("", text, count=1).strip()
    if not normalized:
        raise SkillError("invalid_payload", "移除外层题号后，correctedText 不能为空。")
    return normalized


def _load_json(path_value: str) -> dict[str, JSONValue]:
    if path_value == "-":
        content = sys.stdin.read()
    else:
        path = Path(path_value).expanduser().resolve()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            raise SkillError("input_unreadable", "无法读取指定 JSON 文件。") from None
    try:
        decoded: JSONValue = json.loads(content)
    except json.JSONDecodeError:
        raise SkillError("invalid_payload", "输入不是有效 JSON。") from None
    return _object(decoded, "JSON 输入")


def _relative_path(path_value: str, *, create_parent: bool) -> Path:
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts:
        raise SkillError("unsafe_path", "输出和会话文件必须位于当前工作目录内。")
    resolved = (Path.cwd() / path).resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise SkillError("unsafe_path", "路径超出当前工作目录。")
    if create_parent:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _output_directory(path_value: str) -> Path:
    path = _relative_path(path_value, create_parent=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path_value: str, value: dict[str, JSONValue]) -> str:
    path = _relative_path(path_value, create_parent=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.relative_to(Path.cwd().resolve()).as_posix()


def _start_summary(manifest: dict[str, JSONValue], output: str) -> dict[str, JSONValue]:
    source = _object(manifest.get("source"), "source")
    detection = manifest.get("detection")
    candidate_count = 0
    provider: JSONValue = None
    if isinstance(detection, dict):
        candidate_count = len(_list(detection.get("candidates"), "candidates"))
        provider = detection.get("provider")
    return {
        "mode": manifest.get("mode"),
        "session": output,
        "assetId": source.get("assetId"),
        "fileName": source.get("fileName"),
        "width": source.get("width"),
        "height": source.get("height"),
        "webUrl": manifest.get("webUrl"),
        "detectionProvider": provider,
        "candidateCount": candidate_count,
        "problems": manifest.get("problems"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect corrected math problems into Lark Base")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("SHI_HOMEWORK2LARK_API_URL", DEFAULT_API_URL),
    )
    parser.add_argument(
        "--web-url",
        default=os.environ.get("SHI_HOMEWORK2LARK_WEB_URL", DEFAULT_WEB_URL),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health")

    metadata = commands.add_parser("validate-metadata")
    metadata.add_argument("--input", required=True)

    start = commands.add_parser("start")
    start.add_argument("--file", required=True)
    start.add_argument("--mode", choices=("web", "chat", "single"), required=True)
    start.add_argument("--output", required=True)

    select = commands.add_parser("select")
    select.add_argument("--session", required=True)
    select.add_argument("--candidate-id", action="append", required=True)
    select.add_argument("--output", required=True)

    for command in ("ocr", "get", "publish"):
        child = commands.add_parser(command)
        child.add_argument("--problem-id", required=True)

    revision = commands.add_parser("save-revision")
    revision.add_argument("--problem-id", required=True)
    revision.add_argument("--input", required=True)

    download = commands.add_parser("download-evidence")
    download.add_argument("--problem-id", required=True)
    download.add_argument("--output-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = IntakeService(HttpGateway(args.api_url), web_url=args.web_url)
    try:
        if args.command == "health":
            result: JSONValue = service.health()
        elif args.command == "validate-metadata":
            result = validate_metadata_payload(_load_json(args.input))
        elif args.command == "start":
            manifest = service.start(Path(args.file).expanduser().resolve(), args.mode)
            output = _write_json(args.output, manifest)
            result = _start_summary(manifest, output)
        elif args.command == "select":
            session = _load_json(args.session)
            selection = service.select(session, args.candidate_id)
            output = _write_json(args.output, selection)
            result = {
                "selection": output,
                "selectedCandidateIds": selection["selectedCandidateIds"],
                "problems": selection["problems"],
            }
        elif args.command == "ocr":
            result = service.ocr(args.problem_id)
        elif args.command == "get":
            result = service.get(args.problem_id)
        elif args.command == "save-revision":
            result = service.save_revision(args.problem_id, _load_json(args.input))
        elif args.command == "publish":
            result = service.publish(args.problem_id)
        elif args.command == "download-evidence":
            result = service.download_evidence(args.problem_id, _output_directory(args.output_dir))
        else:
            raise SkillError("unsupported_command", "不支持的命令。")
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except SkillError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "retryable": exc.retryable,
                        **({"requestId": exc.request_id} if exc.request_id else {}),
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
