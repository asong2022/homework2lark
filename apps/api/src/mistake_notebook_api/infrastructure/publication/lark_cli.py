from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar, Protocol

from mistake_notebook_api.domain.errors import JsonValue
from mistake_notebook_api.domain.publication import (
    ProblemPublicationRequest,
    ProblemPublicationResult,
    ProblemPublisherError,
)

CHINA_STANDARD_TIME = timezone(timedelta(hours=8))
_RECORD_PAGE_SIZE = 200


@dataclass(frozen=True)
class _ResolvedTable:
    table_id: str
    stable_field: str
    attachment_field: str
    hash_field: str | None = None
    sequence_field: str | None = None
    title_field: str | None = None
    link_field: str | None = None
    image_name_field: str | None = None
    fields: dict[str, str] | None = None


class LarkCliRunner(Protocol):
    def run(self, args: Sequence[str], *, cwd: Path) -> dict[str, JsonValue]: ...


class SubprocessLarkCliRunner:
    def __init__(self, *, command: str, timeout_seconds: int) -> None:
        self._command = shutil.which(command) or command
        self._timeout_seconds = timeout_seconds

    def run(self, args: Sequence[str], *, cwd: Path) -> dict[str, JsonValue]:
        environment = os.environ.copy()
        environment["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        environment["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        try:
            completed = subprocess.run(
                [self._command, *args],
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            raise ProblemPublisherError("configuration_error") from None
        except subprocess.TimeoutExpired:
            raise ProblemPublisherError("timeout") from None
        except OSError:
            raise ProblemPublisherError("unavailable") from None

        if completed.returncode != 0:
            lowered = completed.stderr.lower()
            category = (
                "configuration_error"
                if any(
                    marker in lowered
                    for marker in ("auth", "permission", "scope", "not configured", "login")
                )
                else "unavailable"
            )
            raise ProblemPublisherError(category)
        try:
            payload: JsonValue = json.loads(completed.stdout)
        except (json.JSONDecodeError, UnicodeError):
            raise ProblemPublisherError("invalid_response") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ProblemPublisherError("invalid_response")
        return payload


class LarkCliProblemPublisher:
    _LEGACY_PAGE_FIELDS: ClassVar[dict[str, str]] = {
        "页面唯一ID": "text",
        "图片名": "text",
        "原始页面图片": "attachment",
    }
    _LEGACY_QUESTION_FIELDS: ClassVar[dict[str, str]] = {
        "题目唯一ID": "text",
        "页面唯一ID": "link",
        "图片题目": "attachment",
        "题干文本": "text",
        "OCR Provider": "select",
        "本地修订版本": "number",
        "已审核时间": "datetime",
    }
    _TARGET_PAGE_FIELDS: ClassVar[dict[str, str]] = {
        "页面名称": "text",
        "系统页面ID": "text",
        "源文件哈希": "text",
        "原始页面图片": "attachment",
    }
    _TARGET_QUESTION_FIELDS: ClassVar[dict[str, str]] = {
        "题目名称": "text",
        "系统题目ID": "text",
        "所属错题页面": "link",
        "图片题目": "attachment",
        "题干图片": "attachment",
        "题干文本": "text",
        "OCR Provider": "select",
        "本地修订版本": "number",
        "已审核时间": "datetime",
    }

    # Kept as a compatibility surface for older contract fixtures.
    _PAGE_FIELDS = _LEGACY_PAGE_FIELDS
    _QUESTION_FIELDS = _LEGACY_QUESTION_FIELDS

    def __init__(
        self,
        *,
        runner: LarkCliRunner,
        base_title: str,
        working_directory: Path | None = None,
    ) -> None:
        self._runner = runner
        self._base_title = base_title
        self._working_directory = (working_directory or Path.cwd()).resolve()

    @property
    def name(self) -> str:
        return "lark_cli"

    def publish(self, request: ProblemPublicationRequest) -> ProblemPublicationResult:
        base_token, base_name = self._resolve_base()
        tables = self._resolve_tables(base_token)
        page_table = self._resolve_page_table(base_token, tables["pages"])
        question_table = self._resolve_question_table(base_token, tables["questions"])
        pages_table_id = page_table.table_id
        questions_table_id = question_table.table_id

        page_record_id, page_cells = self._find_one(
            base_token=base_token,
            table_id=pages_table_id,
            stable_field=page_table.stable_field,
            stable_value=request.source_asset_id,
            projected_fields=self._page_projection(page_table),
        )
        if page_record_id is not None and page_table.hash_field is not None:
            stored_hash = page_cells.get(page_table.hash_field)
            if _has_value(stored_hash) and stored_hash != request.source_file_hash:
                raise ProblemPublisherError("invalid_response")
        reused_by_hash = False
        if page_record_id is None and page_table.hash_field is not None:
            page_record_id, page_cells = self._find_one(
                base_token=base_token,
                table_id=pages_table_id,
                stable_field=page_table.hash_field,
                stable_value=request.source_file_hash,
                projected_fields=self._page_projection(page_table),
            )
            reused_by_hash = page_record_id is not None

        page_values: dict[str, JsonValue] = {}
        if not reused_by_hash:
            page_values[page_table.stable_field] = request.source_asset_id
            if page_table.hash_field is not None:
                page_values[page_table.hash_field] = request.source_file_hash
        if page_table.title_field is not None and not _has_value(
            page_cells.get(page_table.title_field)
        ):
            page_values[page_table.title_field] = _fallback_page_title(request.source_file_name)
        elif page_record_id is None and page_table.sequence_field is not None:
            page_values[page_table.sequence_field] = self._next_sequence(
                base_token=base_token,
                table_id=pages_table_id,
                sequence_field=page_table.sequence_field,
            )
        if page_table.image_name_field is not None and not reused_by_hash:
            page_values[page_table.image_name_field] = request.source_file_name
        if page_values:
            page_record_id = self._upsert(
                base_token=base_token,
                table_id=pages_table_id,
                record_id=page_record_id,
                fields=page_values,
            )
        if page_record_id is None:
            raise ProblemPublisherError("invalid_response")
        if not _has_value(page_cells.get(page_table.attachment_field)):
            self._upload_attachment(
                base_token=base_token,
                table_id=pages_table_id,
                record_id=page_record_id,
                field_id=self._field_id(page_table, page_table.attachment_field),
                file_name=_safe_image_name(
                    request.source_file_name, request.source_media_type, fallback="source.png"
                ),
                data=request.source_image_bytes,
            )

        question_record_id, question_cells = self._find_one(
            base_token=base_token,
            table_id=questions_table_id,
            stable_field=question_table.stable_field,
            stable_value=request.problem_id,
            projected_fields=(
                question_table.stable_field,
                question_table.attachment_field,
                *((question_table.title_field,) if question_table.title_field is not None else ()),
            ),
        )
        reviewed_at = request.reviewed_at.astimezone(CHINA_STANDARD_TIME).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        question_values: dict[str, JsonValue] = {
            question_table.stable_field: request.problem_id,
            self._required_link_field(question_table): [{"id": page_record_id}],
            "题干文本": request.corrected_text,
            "OCR Provider": request.ocr_provider,
            "本地修订版本": request.revision_number,
            "已审核时间": reviewed_at,
        }
        if question_table.title_field is not None and not _has_value(
            question_cells.get(question_table.title_field)
        ):
            question_values[question_table.title_field] = _fallback_question_title(
                request.corrected_text
            )
        elif question_record_id is None and question_table.sequence_field is not None:
            question_values[question_table.sequence_field] = self._next_sequence(
                base_token=base_token,
                table_id=questions_table_id,
                sequence_field=question_table.sequence_field,
            )
        question_record_id = self._upsert(
            base_token=base_token,
            table_id=questions_table_id,
            record_id=question_record_id,
            fields=question_values,
        )
        if not _has_value(question_cells.get(question_table.attachment_field)):
            self._upload_attachment(
                base_token=base_token,
                table_id=questions_table_id,
                record_id=question_record_id,
                field_id=self._field_id(question_table, question_table.attachment_field),
                file_name=f"{request.problem_id}.png",
                data=request.crop_image_bytes,
            )

        return ProblemPublicationResult(
            base_name=base_name,
            pages_table_id=pages_table_id,
            questions_table_id=questions_table_id,
            page_record_id=page_record_id,
            question_record_id=question_record_id,
        )

    def _resolve_base(self) -> tuple[str, str]:
        payload = self._call(
            "base",
            "+title-resolve",
            "--title",
            self._base_title,
            "--as",
            "user",
        )
        data = _dict(payload.get("data"))
        if isinstance(data.get("base_token"), str):
            return (
                _non_empty_string(data.get("base_token")),
                _non_empty_string(data.get("title")),
            )

        candidates = data.get("candidates")
        if not isinstance(candidates, list):
            raise ProblemPublisherError("invalid_response")

        matches: list[tuple[str, str]] = []
        failures: list[ProblemPublisherError] = []
        seen_tokens: set[str] = set()
        for value in candidates:
            candidate = _dict(value)
            title = candidate.get("title")
            token = candidate.get("base_token")
            if title != self._base_title or not isinstance(token, str) or not token.strip():
                continue
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            try:
                self._resolve_tables(token)
            except ProblemPublisherError as exc:
                failures.append(exc)
                continue
            matches.append((token, title))

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ProblemPublisherError("configuration_error")
        if failures:
            raise failures[0]
        raise ProblemPublisherError("configuration_error")

    def _resolve_tables(self, base_token: str) -> dict[str, str]:
        payload = self._call("base", "+table-list", "--base-token", base_token, "--as", "user")
        data = _dict(payload.get("data"))
        tables_value = data.get("tables")
        if not isinstance(tables_value, list):
            raise ProblemPublisherError("invalid_response")
        tables: dict[str, str] = {}
        for value in tables_value:
            table = _dict(value)
            name = _non_empty_string(table.get("name"))
            table_id = _non_empty_string(table.get("id"))
            tables[name] = table_id
        page_matches = [name for name in ("错题页面", "pages") if name in tables]
        question_matches = [name for name in ("错题题目", "questions") if name in tables]
        if len(page_matches) != 1 or len(question_matches) != 1:
            raise ProblemPublisherError("configuration_error")
        return {
            "pages": tables[page_matches[0]],
            "questions": tables[question_matches[0]],
        }

    def _read_fields(self, base_token: str, table_id: str) -> dict[str, tuple[str, str]]:
        payload = self._call(
            "base",
            "+field-list",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--as",
            "user",
        )
        data = _dict(payload.get("data"))
        fields_value = data.get("fields")
        if not isinstance(fields_value, list):
            raise ProblemPublisherError("invalid_response")
        fields: dict[str, tuple[str, str]] = {}
        for value in fields_value:
            field = _dict(value)
            name = _non_empty_string(field.get("name"))
            if name in fields:
                raise ProblemPublisherError("configuration_error")
            fields[name] = (
                _non_empty_string(field.get("id")),
                _non_empty_string(field.get("type")),
            )
        return fields

    def _resolve_page_table(self, base_token: str, table_id: str) -> _ResolvedTable:
        fields = self._read_fields(base_token, table_id)
        stable_field = "系统页面ID" if "系统页面ID" in fields else "页面唯一ID"
        required = {
            stable_field: "text",
            "原始页面图片": "attachment",
        }
        hash_field = None
        if stable_field == "系统页面ID":
            required["源文件哈希"] = "text"
            hash_field = "源文件哈希"
        self._require_fields(fields, required)
        title_field = "页面名称" if fields.get("页面名称", ("", ""))[1] == "text" else None
        sequence_field = (
            "序号" if title_field is None and fields.get("序号", ("", ""))[1] == "text" else None
        )
        image_name_field = "图片名" if fields.get("图片名", ("", ""))[1] == "text" else None
        return _ResolvedTable(
            table_id=table_id,
            stable_field=stable_field,
            attachment_field="原始页面图片",
            hash_field=hash_field,
            sequence_field=sequence_field,
            title_field=title_field,
            image_name_field=image_name_field,
            fields={name: value[0] for name, value in fields.items()},
        )

    def _resolve_question_table(self, base_token: str, table_id: str) -> _ResolvedTable:
        fields = self._read_fields(base_token, table_id)
        stable_field = "系统题目ID" if "系统题目ID" in fields else "题目唯一ID"
        link_field = "所属错题页面" if "所属错题页面" in fields else "页面唯一ID"
        required = {
            stable_field: "text",
            link_field: "link",
            "图片题目": "attachment",
            "题干文本": "text",
            "OCR Provider": "select",
            "本地修订版本": "number",
            "已审核时间": "datetime",
        }
        if stable_field == "系统题目ID":
            required["题干图片"] = "attachment"
        self._require_fields(fields, required)
        title_field = "题目名称" if fields.get("题目名称", ("", ""))[1] == "text" else None
        sequence_field = (
            "错题序号"
            if title_field is None and fields.get("错题序号", ("", ""))[1] == "text"
            else None
        )
        return _ResolvedTable(
            table_id=table_id,
            stable_field=stable_field,
            attachment_field="图片题目",
            sequence_field=sequence_field,
            title_field=title_field,
            link_field=link_field,
            fields={name: value[0] for name, value in fields.items()},
        )

    @staticmethod
    def _require_fields(fields: dict[str, tuple[str, str]], expected: dict[str, str]) -> None:
        for name, field_type in expected.items():
            if name not in fields or fields[name][1] != field_type:
                raise ProblemPublisherError("configuration_error")

    @staticmethod
    def _field_id(table: _ResolvedTable, field_name: str) -> str:
        if table.fields is None or field_name not in table.fields:
            raise ProblemPublisherError("configuration_error")
        return table.fields[field_name]

    @staticmethod
    def _page_projection(table: _ResolvedTable) -> tuple[str, ...]:
        fields = [table.stable_field, table.attachment_field]
        if table.hash_field is not None:
            fields.append(table.hash_field)
        if table.title_field is not None:
            fields.append(table.title_field)
        return tuple(fields)

    @staticmethod
    def _required_link_field(table: _ResolvedTable) -> str:
        if table.link_field is None:
            raise ProblemPublisherError("configuration_error")
        return table.link_field

    def _next_sequence(self, *, base_token: str, table_id: str, sequence_field: str) -> str:
        values: set[int] = set()
        offset = 0
        while True:
            records = _columnar_records(
                self._call(
                    "base",
                    "+record-list",
                    "--base-token",
                    base_token,
                    "--table-id",
                    table_id,
                    "--field-id",
                    sequence_field,
                    "--offset",
                    str(offset),
                    "--limit",
                    str(_RECORD_PAGE_SIZE),
                    "--format",
                    "json",
                    "--as",
                    "user",
                )
            )
            for _, cells in records:
                value = cells.get(sequence_field)
                if value in (None, ""):
                    continue
                if not isinstance(value, str) or not value.isdigit() or int(value) < 1:
                    raise ProblemPublisherError("configuration_error")
                number = int(value)
                if number in values:
                    raise ProblemPublisherError("configuration_error")
                values.add(number)
            if len(records) < _RECORD_PAGE_SIZE:
                break
            offset += len(records)
        return str(max(values, default=0) + 1)

    def _find_one(
        self,
        *,
        base_token: str,
        table_id: str,
        stable_field: str,
        stable_value: str,
        projected_fields: tuple[str, ...],
    ) -> tuple[str | None, dict[str, JsonValue]]:
        filter_json = json.dumps(
            {"logic": "and", "conditions": [[stable_field, "==", stable_value]]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        args = [
            "base",
            "+record-list",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--filter-json",
            filter_json,
            "--limit",
            "2",
            "--format",
            "json",
            "--as",
            "user",
        ]
        for field in projected_fields:
            args.extend(("--field-id", field))
        records = _columnar_records(self._call(*args))
        if len(records) > 1:
            raise ProblemPublisherError("duplicate_remote_record")
        if not records:
            return None, {}
        return records[0]

    def _upsert(
        self,
        *,
        base_token: str,
        table_id: str,
        record_id: str | None,
        fields: dict[str, JsonValue],
    ) -> str:
        args = [
            "base",
            "+record-upsert",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
        ]
        if record_id is not None:
            args.extend(("--record-id", record_id))
        args.extend(
            (
                "--json",
                json.dumps(fields, ensure_ascii=False, separators=(",", ":")),
                "--as",
                "user",
            )
        )
        payload = self._call(*args)
        if record_id is not None:
            return record_id
        return _created_record_id(payload)

    def _upload_attachment(
        self,
        *,
        base_token: str,
        table_id: str,
        record_id: str,
        field_id: str,
        file_name: str,
        data: bytes,
    ) -> None:
        with TemporaryDirectory(prefix=".lark-publish-", dir=self._working_directory) as directory:
            path = Path(directory) / file_name
            path.write_bytes(data)
            relative_path = path.relative_to(self._working_directory)
            self._call(
                "base",
                "+record-upload-attachment",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--record-id",
                record_id,
                "--field-id",
                field_id,
                "--file",
                relative_path.as_posix(),
                "--as",
                "user",
            )

    def _call(self, *args: str) -> dict[str, JsonValue]:
        return self._runner.run(args, cwd=self._working_directory)


def _dict(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ProblemPublisherError("invalid_response")
    return value


def _non_empty_string(value: JsonValue) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProblemPublisherError("invalid_response")
    return value


def _columnar_records(
    payload: dict[str, JsonValue],
) -> list[tuple[str, dict[str, JsonValue]]]:
    data = _dict(payload.get("data"))
    record_ids = data.get("record_id_list")
    fields = data.get("fields")
    rows = data.get("data")
    if (
        not isinstance(record_ids, list)
        or not isinstance(fields, list)
        or not isinstance(rows, list)
    ):
        raise ProblemPublisherError("invalid_response")
    if len(record_ids) != len(rows) or not all(isinstance(field, str) for field in fields):
        raise ProblemPublisherError("invalid_response")
    output: list[tuple[str, dict[str, JsonValue]]] = []
    field_names = [field for field in fields if isinstance(field, str)]
    for record_id_value, row_value in zip(record_ids, rows, strict=True):
        record_id = _non_empty_string(record_id_value)
        if not isinstance(row_value, list) or len(row_value) != len(field_names):
            raise ProblemPublisherError("invalid_response")
        output.append((record_id, dict(zip(field_names, row_value, strict=True))))
    return output


def _created_record_id(payload: dict[str, JsonValue]) -> str:
    data = _dict(payload.get("data"))
    record = data.get("record")
    if isinstance(record, dict):
        record_ids = record.get("record_id_list")
        if isinstance(record_ids, list) and len(record_ids) == 1:
            return _non_empty_string(record_ids[0])
        found = _find_record_id(record)
        if found is not None:
            return found
    raise ProblemPublisherError("invalid_response")


def _find_record_id(value: JsonValue) -> str | None:
    if isinstance(value, dict):
        for key in ("record_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith("rec"):
                return candidate
        for nested in value.values():
            found = _find_record_id(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_record_id(nested)
            if found is not None:
                return found
    return None


def _has_value(value: JsonValue | None) -> bool:
    return value not in (None, "", [])


def _fallback_page_title(file_name: str) -> str:
    stem = Path(file_name.replace("\\", "/")).stem
    return _fallback_catalog_title("待整理页面", stem)


def _fallback_question_title(corrected_text: str) -> str:
    return _fallback_catalog_title("待整理题目", corrected_text)


def _fallback_catalog_title(prefix: str, value: str) -> str:
    normalized = " ".join(value.split()).strip("，。；：:!?！？ ")
    excerpt = normalized[:28].rstrip("，。；：:!?！？ ") or "未命名"
    return f"{prefix}·{excerpt}"[:80]


def _safe_image_name(file_name: str, media_type: str, *, fallback: str) -> str:
    name = Path(file_name.replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    allowed = {".jpg", ".jpeg", ".png"}
    if suffix not in allowed:
        suffix = {"image/jpeg": ".jpg", "image/png": ".png"}.get(media_type, ".png")
        name = f"{Path(name).stem or Path(fallback).stem}{suffix}"
    return name[:200] or fallback
