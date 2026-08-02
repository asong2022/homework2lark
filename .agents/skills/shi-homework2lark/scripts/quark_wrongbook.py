#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from intake import (  # noqa: E402, I001
    DEFAULT_API_URL,
    HttpGateway,
    IntakeService,
    SkillError as IntakeSkillError,
)

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

STATE_VERSION = "quark-wrongbook-state-v1"
VALID_STATUSES = frozenset(("baseline_excluded", "pending", "imported", "ignored"))
LIST_HOST = "https://qknow-node-service.quark.cn"
STAT_HOST = "https://study-iflow.quark.cn"
LIST_PATH = "/c/api/souti/notebook/list?uc_param_str=utkpddprfrlove"
STAT_PATH = "/v1/api/cuotiben/course/stat"
PAGE_SIZE = 50
MAX_PAGES_PER_COURSE = 500
MAX_IMAGE_BYTES = 15 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Mobile UCBrowser/13.4.0.1308"
QUESTION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
PROBLEM_ID_RE = re.compile(r"^problem_[A-Za-z0-9_-]+$")


class WrongbookError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, JSONValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


@dataclass(frozen=True)
class RemoteQuestion:
    question_id: str
    image_url: str | None


@dataclass(frozen=True)
class DownloadedImage:
    data: bytes
    suffix: str


class WrongbookClient(Protocol):
    def list_questions(self) -> list[RemoteQuestion]: ...

    def download_image(self, question: RemoteQuestion) -> DownloadedImage: ...


class ProblemImporter(Protocol):
    def import_image(self, image: DownloadedImage) -> str: ...


class SingleIntakeService(Protocol):
    def start(self, path: Path, mode: str) -> dict[str, JSONValue]: ...


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict[str, JSONValue]:
        if not self.path.is_file():
            raise WrongbookError(
                "baseline_required",
                "尚未建立夸克错题本基线，请先执行 baseline。",
            )
        try:
            raw: JSONValue = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise WrongbookError("state_invalid", "夸克错题本本地状态无法读取。") from None
        return _validate_state(raw)

    def save(self, state: dict[str, JSONValue]) -> None:
        validated = _validate_state(state)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp_path = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
            payload = json.dumps(validated, ensure_ascii=False, indent=2) + "\n"
            descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.path)
            except OSError:
                temp_path.unlink(missing_ok=True)
                raise
        except (OSError, UnicodeError):
            raise WrongbookError(
                "state_write_failed",
                "夸克错题本本地状态保存失败，旧状态保持不变。",
                retryable=True,
            ) from None


class QuarkHttpClient:
    def __init__(
        self,
        *,
        ut: str,
        kp: str,
        timeout_seconds: int = 20,
        opener: Callable[..., object] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not ut.strip() or not kp.strip():
            raise WrongbookError(
                "quark_credentials_missing",
                "夸克错题本连接信息未配置，请让 AI 安全设置 QK_UT 和 QK_KP。",
            )
        self._ut = ut.strip()
        self._kp = kp.strip()
        self._timeout_seconds = timeout_seconds
        self._opener = opener
        self._sleep = sleep

    @classmethod
    def from_environment(cls) -> QuarkHttpClient:
        return cls(ut=os.environ.get("QK_UT", ""), kp=os.environ.get("QK_KP", ""))

    def list_questions(self) -> list[RemoteQuestion]:
        courses = self._courses()
        questions: dict[str, RemoteQuestion] = {}
        for course in courses:
            seen_pages: set[tuple[str, ...]] = set()
            for page in range(1, MAX_PAGES_PER_COURSE + 1):
                response = self._request_json(
                    LIST_HOST,
                    LIST_PATH,
                    {"page": page, "size": PAGE_SIZE, "course": course},
                )
                data = _response_data_object(response)
                raw_questions = data.get("question_list", [])
                if not isinstance(raw_questions, list):
                    raise WrongbookError(
                        "quark_invalid_response",
                        "夸克错题本返回的题目列表结构已变化。",
                    )
                page_questions = [_remote_question(value) for value in raw_questions]
                signature = tuple(question.question_id for question in page_questions)
                if signature and signature in seen_pages:
                    raise WrongbookError(
                        "quark_pagination_repeated",
                        "夸克错题本分页重复，已停止同步以避免漏题或死循环。",
                        retryable=True,
                    )
                seen_pages.add(signature)
                for question in page_questions:
                    existing = questions.get(question.question_id)
                    if existing is None:
                        questions[question.question_id] = question
                    else:
                        questions[question.question_id] = _merge_duplicate(existing, question)
                if len(page_questions) < PAGE_SIZE:
                    break
                self._sleep(0.2)
            else:
                raise WrongbookError(
                    "quark_page_limit",
                    "夸克错题本分页超过安全上限，已停止同步。",
                    retryable=True,
                )
        return list(questions.values())

    def download_image(self, question: RemoteQuestion) -> DownloadedImage:
        if question.image_url is None:
            raise WrongbookError(
                "quark_image_missing",
                "所选夸克错题没有可用原题图片，请在夸克中补全后重试。",
            )
        _validate_download_url(question.image_url)
        request = urllib.request.Request(
            question.image_url,
            headers={"User-Agent": USER_AGENT},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                final_url = getattr(response, "geturl", lambda: question.image_url)()
                if not isinstance(final_url, str):
                    raise WrongbookError(
                        "quark_image_url_invalid",
                        "夸克错题图片地址无效。",
                    )
                _validate_download_url(final_url)
                data = response.read(MAX_IMAGE_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise WrongbookError(
                "quark_image_http_error",
                "夸克错题图片下载失败，请稍后重试。",
                retryable=error.code == 429 or error.code >= 500,
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise WrongbookError(
                "quark_image_unavailable",
                "夸克错题图片暂时无法下载，请稍后重试。",
                retryable=True,
            ) from None
        if len(data) > MAX_IMAGE_BYTES:
            raise WrongbookError("quark_image_too_large", "夸克错题图片超过大小限制。")
        return DownloadedImage(data=data, suffix=_image_suffix(data))

    def _courses(self) -> list[str]:
        response = self._request_json(STAT_HOST, STAT_PATH, {})
        raw = response.get("data")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise WrongbookError(
                "quark_invalid_response",
                "夸克错题本返回的课程结构已变化。",
            )
        courses: list[str] = []
        for value in raw:
            if not isinstance(value, dict):
                raise WrongbookError(
                    "quark_invalid_response",
                    "夸克错题本返回的课程结构已变化。",
                )
            if not value.get("total_question"):
                continue
            course = value.get("course")
            if not isinstance(course, str):
                raise WrongbookError(
                    "quark_invalid_response",
                    "夸克错题本返回的课程标识无效。",
                )
            if course not in courses:
                courses.append(course)
        return courses or [""]

    def _request_json(
        self,
        host: str,
        path: str,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        separator = "&" if "?" in path else "?"
        query = urllib.parse.urlencode({"ut": self._ut, "kp": self._kp})
        request = urllib.request.Request(
            f"{host}{path}{separator}{query}",
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Origin": "https://vt.quark.cn",
                "Referer": "https://vt.quark.cn/",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                decoded: JSONValue = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise WrongbookError(
                "quark_http_error",
                "夸克错题本暂时无法访问，请稍后重试。",
                retryable=error.code == 429 or error.code >= 500,
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise WrongbookError(
                "quark_unavailable",
                "夸克错题本暂时无法访问，请稍后重试。",
                retryable=True,
            ) from None
        except (json.JSONDecodeError, UnicodeError):
            raise WrongbookError(
                "quark_invalid_response",
                "夸克错题本返回了无法识别的数据。",
            ) from None
        if not isinstance(decoded, dict):
            raise WrongbookError(
                "quark_invalid_response",
                "夸克错题本返回的数据结构无效。",
            )
        return decoded


class LazyQuarkClient:
    def __init__(self) -> None:
        self._client: QuarkHttpClient | None = None

    def list_questions(self) -> list[RemoteQuestion]:
        return self._get().list_questions()

    def download_image(self, question: RemoteQuestion) -> DownloadedImage:
        return self._get().download_image(question)

    def _get(self) -> QuarkHttpClient:
        if self._client is None:
            self._client = QuarkHttpClient.from_environment()
        return self._client


class SingleIntakeImporter:
    def __init__(
        self,
        api_url: str,
        *,
        service: SingleIntakeService | None = None,
    ) -> None:
        self._service = service or IntakeService(HttpGateway(api_url))

    def import_image(self, image: DownloadedImage) -> str:
        try:
            with tempfile.TemporaryDirectory(prefix="homework2lark-quark-") as directory:
                path = Path(directory) / f"question{image.suffix}"
                path.write_bytes(image.data)
                manifest = self._service.start(path, "single")
        except IntakeSkillError as error:
            raise WrongbookError(
                error.code,
                error.message,
                retryable=error.retryable,
            ) from None
        problems = manifest.get("problems")
        if not isinstance(problems, list) or len(problems) != 1:
            raise WrongbookError(
                "single_import_invalid_response",
                "本地错题服务没有返回唯一题目，请重试。",
            )
        problem = problems[0]
        if not isinstance(problem, dict):
            raise WrongbookError(
                "single_import_invalid_response",
                "本地错题服务返回的题目结构无效。",
            )
        return _problem_id(problem.get("problemId"))


class WrongbookService:
    def __init__(
        self,
        store: StateStore,
        *,
        client: WrongbookClient | None = None,
        importer: ProblemImporter | None = None,
        now: Callable[[], str] = lambda: datetime.now(UTC).isoformat(),
    ) -> None:
        self._store = store
        self._client = client
        self._importer = importer
        self._now = now

    def baseline(self) -> dict[str, JSONValue]:
        if self._store.exists():
            state = self._store.load()
            return {
                "status": "no_change",
                **_state_summary(state),
                "downloadedCount": 0,
                "problemCreatedCount": 0,
            }
        questions = self._require_client().list_questions()
        now = self._now()
        items: dict[str, JSONValue] = {
            question.question_id: {
                "status": "baseline_excluded",
                "firstSeenAt": now,
                "updatedAt": now,
            }
            for question in questions
        }
        state: dict[str, JSONValue] = {
            "schemaVersion": STATE_VERSION,
            "createdAt": now,
            "updatedAt": now,
            "items": items,
        }
        self._store.save(state)
        return {
            "status": "initialized",
            **_state_summary(state),
            "downloadedCount": 0,
            "problemCreatedCount": 0,
        }

    def sync(self) -> dict[str, JSONValue]:
        state = self._store.load()
        questions = self._require_client().list_questions()
        discovered = self._discover(state, questions)
        return {
            "status": "synced" if discovered else "no_change",
            "discoveredCount": discovered,
            **_state_summary(state),
        }

    def collect_new(self) -> dict[str, JSONValue]:
        state = self._store.load()
        questions = self._require_client().list_questions()
        discovered = self._discover(state, questions)
        pending = [
            question_id
            for question_id, value in _state_items(state).items()
            if _item(value)["status"] == "pending"
        ]
        if not pending:
            return {
                "status": "no_change",
                "discoveredCount": discovered,
                "downloadedCount": 0,
                "problemCreatedCount": 0,
                "imported": [],
                "unchanged": [],
                **_state_summary(state),
            }
        result = self._import_from_state(
            state,
            pending,
            catalog=_question_catalog(questions),
        )
        return {
            **result,
            "discoveredCount": discovered,
            "downloadedCount": len(pending),
            "problemCreatedCount": len(pending),
        }

    def status(self) -> dict[str, JSONValue]:
        return {"status": "ready", **_state_summary(self._store.load())}

    def ignore(self, question_ids: Sequence[str]) -> dict[str, JSONValue]:
        selected = _selected_ids(question_ids)
        state = self._store.load()
        items = _state_items(state)
        _validate_transitions(items, selected, allowed=frozenset(("pending", "ignored")))
        now = self._now()
        changed = 0
        for question_id in selected:
            item = _item(items[question_id])
            if item["status"] == "ignored":
                continue
            item["status"] = "ignored"
            item["updatedAt"] = now
            changed += 1
        if changed:
            state["updatedAt"] = now
            self._store.save(state)
        return {
            "status": "ignored" if changed else "no_change",
            "ignoredNowCount": changed,
            **_state_summary(state),
        }

    def import_questions(
        self,
        question_ids: Sequence[str] = (),
        *,
        all_pending: bool = False,
    ) -> dict[str, JSONValue]:
        state = self._store.load()
        items = _state_items(state)
        selected = (
            [key for key, value in items.items() if _item(value)["status"] == "pending"]
            if all_pending
            else _selected_ids(question_ids)
        )
        return self._import_from_state(state, selected)

    def _discover(
        self,
        state: dict[str, JSONValue],
        questions: Sequence[RemoteQuestion],
    ) -> int:
        items = _state_items(state)
        now = self._now()
        discovered = 0
        for question in questions:
            if question.question_id in items:
                continue
            items[question.question_id] = {
                "status": "pending",
                "firstSeenAt": now,
                "updatedAt": now,
            }
            discovered += 1
        if discovered:
            state["updatedAt"] = now
            self._store.save(state)
        return discovered

    def _import_from_state(
        self,
        state: dict[str, JSONValue],
        selected: Sequence[str],
        *,
        catalog: dict[str, RemoteQuestion] | None = None,
    ) -> dict[str, JSONValue]:
        items = _state_items(state)
        if not selected:
            return {
                "status": "no_change",
                "imported": [],
                "unchanged": [],
                **_state_summary(state),
            }
        _validate_transitions(items, selected, allowed=frozenset(("pending", "imported")))
        unchanged = [
            {
                "questionId": question_id,
                "problemId": _problem_id(_item(items[question_id]).get("problemId")),
            }
            for question_id in selected
            if _item(items[question_id])["status"] == "imported"
        ]
        pending = [
            question_id
            for question_id in selected
            if _item(items[question_id])["status"] == "pending"
        ]
        if not pending:
            return {
                "status": "no_change",
                "imported": [],
                "unchanged": unchanged,
                **_state_summary(state),
            }
        if catalog is None:
            catalog = _question_catalog(self._require_client().list_questions())
        importer = self._require_importer()
        imported: list[dict[str, JSONValue]] = []
        for question_id in pending:
            question = catalog.get(question_id)
            if question is None:
                raise WrongbookError(
                    "question_unavailable",
                    "待收录错题已不在夸克当前列表中，请稍后重试或明确忽略该题。",
                    details={"questionId": question_id},
                )
            image = self._require_client().download_image(question)
            problem_id = importer.import_image(image)
            now = self._now()
            next_state = _copy_state(state)
            next_items = _state_items(next_state)
            next_items[question_id] = {
                "status": "imported",
                "firstSeenAt": _item(items[question_id])["firstSeenAt"],
                "updatedAt": now,
                "problemId": problem_id,
            }
            next_state["updatedAt"] = now
            try:
                self._store.save(next_state)
            except WrongbookError as error:
                if error.code != "state_write_failed":
                    raise
                raise WrongbookError(
                    error.code,
                    "题目已进入本地错题服务，但增量状态保存失败；"
                    "请保留返回的 problem ID 并让 AI 修复状态。",
                    retryable=True,
                    details={"questionId": question_id, "problemId": problem_id},
                ) from None
            state = next_state
            items = next_items
            imported.append({"questionId": question_id, "problemId": problem_id})
        return {
            "status": "imported",
            "imported": imported,
            "unchanged": unchanged,
            **_state_summary(state),
        }

    def _require_client(self) -> WrongbookClient:
        if self._client is None:
            raise WrongbookError("client_required", "当前命令需要夸克错题本连接。")
        return self._client

    def _require_importer(self) -> ProblemImporter:
        if self._importer is None:
            raise WrongbookError("importer_required", "当前命令需要本地错题服务。")
        return self._importer


def _validate_state(raw: JSONValue) -> dict[str, JSONValue]:
    if not isinstance(raw, dict) or set(raw) != {
        "schemaVersion",
        "createdAt",
        "updatedAt",
        "items",
    }:
        raise WrongbookError("state_invalid", "夸克错题本本地状态结构无效。")
    if raw.get("schemaVersion") != STATE_VERSION:
        raise WrongbookError("state_invalid", "夸克错题本本地状态版本不受支持。")
    _timestamp(raw.get("createdAt"))
    _timestamp(raw.get("updatedAt"))
    items = raw.get("items")
    if not isinstance(items, dict):
        raise WrongbookError("state_invalid", "夸克错题本本地题目状态无效。")
    for question_id, raw_item in items.items():
        _question_id(question_id)
        item = _item(raw_item)
        allowed = {"status", "firstSeenAt", "updatedAt"}
        status = item.get("status")
        if status == "imported":
            allowed.add("problemId")
        if set(item) != allowed or status not in VALID_STATUSES:
            raise WrongbookError("state_invalid", "夸克错题本本地题目状态无效。")
        _timestamp(item.get("firstSeenAt"))
        _timestamp(item.get("updatedAt"))
        if status == "imported":
            _problem_id(item.get("problemId"))
    return raw


def _state_items(state: dict[str, JSONValue]) -> dict[str, JSONValue]:
    items = state.get("items")
    if not isinstance(items, dict):
        raise WrongbookError("state_invalid", "夸克错题本本地题目状态无效。")
    return items


def _item(value: JSONValue) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise WrongbookError("state_invalid", "夸克错题本本地题目状态无效。")
    return value


def _state_summary(state: dict[str, JSONValue]) -> dict[str, JSONValue]:
    items = _state_items(state)
    counts = {status: 0 for status in VALID_STATUSES}
    pending: list[dict[str, JSONValue]] = []
    for question_id, raw_item in items.items():
        item = _item(raw_item)
        status = item.get("status")
        if not isinstance(status, str) or status not in counts:
            raise WrongbookError("state_invalid", "夸克错题本本地题目状态无效。")
        counts[status] += 1
        if status == "pending":
            pending.append({"questionId": question_id, "firstSeenAt": item.get("firstSeenAt")})
    pending.sort(key=lambda value: (str(value["firstSeenAt"]), str(value["questionId"])))
    return {
        "totalCount": len(items),
        "baselineExcludedCount": counts["baseline_excluded"],
        "pendingCount": counts["pending"],
        "importedCount": counts["imported"],
        "ignoredCount": counts["ignored"],
        "pending": pending,
    }


def _copy_state(state: dict[str, JSONValue]) -> dict[str, JSONValue]:
    copied: JSONValue = json.loads(json.dumps(state, ensure_ascii=False))
    if not isinstance(copied, dict):
        raise WrongbookError("state_invalid", "夸克错题本本地状态结构无效。")
    return copied


def _response_data_object(response: dict[str, JSONValue]) -> dict[str, JSONValue]:
    data = response.get("data")
    if not isinstance(data, dict):
        raise WrongbookError(
            "quark_invalid_response",
            "夸克错题本返回的数据结构无效。",
        )
    return data


def _remote_question(value: JSONValue) -> RemoteQuestion:
    if not isinstance(value, dict):
        raise WrongbookError(
            "quark_invalid_response",
            "夸克错题本返回的题目结构无效。",
        )
    question_id = _question_id(value.get("question_id"))
    image_url = value.get("original_image_url")
    if image_url is not None and (not isinstance(image_url, str) or not image_url.strip()):
        raise WrongbookError(
            "quark_invalid_response",
            "夸克错题本返回的原题图片字段无效。",
        )
    return RemoteQuestion(
        question_id=question_id, image_url=image_url.strip() if image_url else None
    )


def _merge_duplicate(first: RemoteQuestion, second: RemoteQuestion) -> RemoteQuestion:
    if first.image_url and second.image_url and first.image_url != second.image_url:
        raise WrongbookError(
            "quark_duplicate_conflict",
            "夸克错题本同一题目返回了冲突图片，已停止同步。",
        )
    return first if first.image_url else second


def _question_catalog(
    questions: Sequence[RemoteQuestion],
) -> dict[str, RemoteQuestion]:
    catalog: dict[str, RemoteQuestion] = {}
    for question in questions:
        existing = catalog.get(question.question_id)
        catalog[question.question_id] = (
            question if existing is None else _merge_duplicate(existing, question)
        )
    return catalog


def _question_id(value: JSONValue) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not QUESTION_ID_RE.fullmatch(value.strip()):
        raise WrongbookError(
            "quark_invalid_response",
            "夸克错题本返回的题目标识无效。",
        )
    return value.strip()


def _problem_id(value: JSONValue) -> str:
    if not isinstance(value, str) or not PROBLEM_ID_RE.fullmatch(value):
        raise WrongbookError("state_invalid", "本地错题 problem ID 无效。")
    return value


def _timestamp(value: JSONValue) -> str:
    if not isinstance(value, str):
        raise WrongbookError("state_invalid", "夸克错题本本地时间字段无效。")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise WrongbookError("state_invalid", "夸克错题本本地时间字段无效。") from None
    if parsed.tzinfo is None:
        raise WrongbookError("state_invalid", "夸克错题本本地时间字段无效。")
    return value


def _selected_ids(values: Sequence[str]) -> list[str]:
    selected = [_question_id(value) for value in values]
    if not selected or len(selected) != len(set(selected)):
        raise WrongbookError("invalid_selection", "请选择一个或多个不重复的夸克题目 ID。")
    return selected


def _validate_transitions(
    items: dict[str, JSONValue],
    selected: Sequence[str],
    *,
    allowed: frozenset[str],
) -> None:
    for question_id in selected:
        if question_id not in items:
            raise WrongbookError("question_not_found", "所选题目不在本地增量状态中。")
        status = _item(items[question_id]).get("status")
        if status not in allowed:
            raise WrongbookError(
                "invalid_state_transition",
                "所选题目的当前状态不允许执行这个操作。",
            )


def _validate_download_url(value: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise WrongbookError("quark_image_url_invalid", "夸克错题图片地址无效。")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        raise WrongbookError("quark_image_url_invalid", "夸克错题图片地址无效。")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise WrongbookError("quark_image_url_invalid", "夸克错题图片地址无效。")


def _image_suffix(data: bytes) -> str:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 16 and data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    raise WrongbookError(
        "quark_image_invalid",
        "夸克错题图片不是可识别的 JPG 或 PNG。",
    )


def _default_state_path() -> Path:
    configured = os.environ.get("SHI_HOMEWORK2LARK_QUARK_STATE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".shi-homework2lark" / "quark-wrongbook-state.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync only new Quark wrongbook questions")
    parser.add_argument("--state", type=Path, default=_default_state_path())
    parser.add_argument(
        "--api-url",
        default=os.environ.get("SHI_HOMEWORK2LARK_API_URL", DEFAULT_API_URL),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("baseline")
    commands.add_parser("sync")
    commands.add_parser("collect-new")
    commands.add_parser("status")

    ignore = commands.add_parser("ignore")
    ignore.add_argument("--question-id", action="append", required=True)

    import_command = commands.add_parser("import")
    selection = import_command.add_mutually_exclusive_group(required=True)
    selection.add_argument("--question-id", action="append")
    selection.add_argument("--all-pending", action="store_true")
    return parser


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with suppress(ValueError, OSError):
            reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    store = StateStore(args.state.expanduser().resolve())
    try:
        if args.command == "status":
            result = WrongbookService(store).status()
        elif args.command == "ignore":
            result = WrongbookService(store).ignore(args.question_id)
        else:
            client = LazyQuarkClient()
            if args.command == "baseline":
                result = WrongbookService(store, client=client).baseline()
            elif args.command == "sync":
                result = WrongbookService(store, client=client).sync()
            elif args.command == "collect-new":
                result = WrongbookService(
                    store,
                    client=client,
                    importer=SingleIntakeImporter(args.api_url),
                ).collect_new()
            else:
                result = WrongbookService(
                    store,
                    client=client,
                    importer=SingleIntakeImporter(args.api_url),
                ).import_questions(
                    args.question_id or (),
                    all_pending=args.all_pending,
                )
    except WrongbookError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "retryable": error.retryable,
                        "details": error.details,
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
