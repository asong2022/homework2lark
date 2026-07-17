#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import homework2lark  # noqa: E402
import intake  # noqa: E402

JSONValue = intake.JSONValue

DEFAULT_BASE_TITLE = "小学数学错题学习库"
PAGE_TABLE = "错题页面"
QUESTION_TABLE = "错题题目"
QUESTION_ID_FIELD = "系统题目ID"
QUESTION_PAGE_LINK_FIELD = "所属错题页面"
QUESTION_LOOKUP_FIELDS = {
    "时间": "时间",
    "年级": "年级",
    "页码": "页码",
    "错题来源": "错题来源",
}

PAGE_FIELD_TYPES = {
    name: ("select" if name in {"错题来源", "年级"} else "datetime" if name == "时间" else "text")
    for name in intake.PAGE_METADATA_FIELDS
}
QUESTION_FIELD_TYPES = {
    name: ("select" if name in {"题型", "核心素养"} else "text")
    for name in intake.QUESTION_METADATA_FIELDS
}


@dataclass(frozen=True)
class EnrichmentRows:
    page: homework2lark.BaseRecord
    question: homework2lark.BaseRecord


class MetadataGateway(Protocol):
    def load(self, problem_id: str) -> EnrichmentRows: ...

    def patch_page(self, record_id: str, patch: dict[str, JSONValue]) -> None: ...

    def patch_question(self, record_id: str, patch: dict[str, JSONValue]) -> None: ...


@dataclass(frozen=True)
class FieldPlan:
    patch: dict[str, JSONValue]
    unchanged: tuple[str, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class EnrichmentPlan:
    problem_id: str
    page_record_id: str
    question_record_id: str
    page: FieldPlan
    question: FieldPlan

    @property
    def conflicts(self) -> tuple[str, ...]:
        return tuple(
            [f"page.{name}" for name in self.page.conflicts]
            + [f"question.{name}" for name in self.question.conflicts]
        )

    @property
    def has_changes(self) -> bool:
        return bool(self.page.patch or self.question.patch)

    def public(self, *, applied: bool = False) -> dict[str, JSONValue]:
        status = "conflict" if self.conflicts else "ready" if self.has_changes else "no_change"
        if applied:
            status = "applied" if self.has_changes else "no_change"
        return {
            "problemId": self.problem_id,
            "status": status,
            "applied": applied and self.has_changes,
            "page": _public_field_plan(self.page),
            "question": _public_field_plan(self.question),
        }


class BaseMetadataService:
    def __init__(self, gateway: MetadataGateway) -> None:
        self.gateway = gateway

    def preview(self, value: JSONValue) -> EnrichmentPlan:
        payload = intake.validate_metadata_payload(value)
        problem_id = _required_string(payload.get("problemId"), "problemId")
        rows = self.gateway.load(problem_id)
        _validate_linked_lookup_values(rows)
        page_values = _object(payload.get("page"), "page")
        question_values = _object(payload.get("question"), "question")
        page_plan = _plan_fields(rows.page.fields, page_values)
        question_plan = _plan_fields(rows.question.fields, question_values)

        return EnrichmentPlan(
            problem_id=problem_id,
            page_record_id=rows.page.record_id,
            question_record_id=rows.question.record_id,
            page=page_plan,
            question=question_plan,
        )

    def apply(self, value: JSONValue) -> dict[str, JSONValue]:
        plan = self.preview(value)
        if plan.conflicts:
            raise intake.SkillError(
                "metadata_conflict",
                "Base 已有不同的非空值；请先在预览中核对冲突字段。",
            )
        if not plan.has_changes:
            return plan.public(applied=True)

        page_written = False
        try:
            if plan.page.patch:
                self.gateway.patch_page(plan.page_record_id, plan.page.patch)
                page_written = True
            if plan.question.patch:
                self.gateway.patch_question(plan.question_record_id, plan.question.patch)
        except (intake.SkillError, homework2lark.SkillError):
            if page_written:
                raise intake.SkillError(
                    "metadata_partial_write",
                    "页面元数据已写入，但题目元数据尚未完成；请用同一输入重试。",
                    retryable=True,
                ) from None
            raise

        readback = self.gateway.load(plan.problem_id)
        _validate_linked_lookup_values(readback)
        _verify_patch(readback.page.fields, plan.page.patch)
        _verify_patch(readback.question.fields, plan.question.patch)
        return plan.public(applied=True)


@dataclass(frozen=True)
class _TableContext:
    table_id: str
    fields: dict[str, homework2lark.BaseField]


class LarkMetadataGateway:
    def __init__(
        self,
        runner: homework2lark.SubprocessRunner,
        *,
        base_title: str = DEFAULT_BASE_TITLE,
    ) -> None:
        self.runner = runner
        self.base_title = base_title
        self._base_token: str | None = None
        self._tables: dict[str, _TableContext] | None = None

    def load(self, problem_id: str) -> EnrichmentRows:
        base_token, tables = self._context()
        question_table = tables[QUESTION_TABLE]
        page_table = tables[PAGE_TABLE]
        question_fields = (
            QUESTION_ID_FIELD,
            QUESTION_PAGE_LINK_FIELD,
            *QUESTION_LOOKUP_FIELDS,
            *sorted(intake.QUESTION_METADATA_FIELDS),
        )
        question_records = self._list_records(
            base_token,
            question_table,
            question_fields,
            filter_json={
                "logic": "and",
                "conditions": [
                    [
                        question_table.fields[QUESTION_ID_FIELD].field_id,
                        "==",
                        problem_id,
                    ]
                ],
            },
        )
        if len(question_records) == 0:
            raise intake.SkillError("record_not_found", "Base 中没有找到这个本地题目。")
        if len(question_records) > 1:
            raise intake.SkillError("duplicate_question_id", "Base 中存在重复的系统题目 ID。")
        question = question_records[0]
        page_record_id = _single_link_id(question.fields.get(QUESTION_PAGE_LINK_FIELD))
        page = self._get_record(
            base_token,
            page_table,
            page_record_id,
            tuple(sorted(intake.PAGE_METADATA_FIELDS)),
        )
        return EnrichmentRows(page=page, question=question)

    def patch_page(self, record_id: str, patch: dict[str, JSONValue]) -> None:
        self._patch(PAGE_TABLE, record_id, patch)

    def patch_question(self, record_id: str, patch: dict[str, JSONValue]) -> None:
        self._patch(QUESTION_TABLE, record_id, patch)

    def _context(self) -> tuple[str, dict[str, _TableContext]]:
        if self._base_token is not None and self._tables is not None:
            return self._base_token, self._tables
        matches: list[tuple[str, dict[str, str]]] = []
        for candidate in homework2lark.resolve_base_candidates(self.runner, self.base_title):
            table_ids: dict[str, str] = {}
            for table in candidate.tables:
                name = table.get("name")
                if name in {PAGE_TABLE, QUESTION_TABLE}:
                    table_ids[_required_string(name, "table.name")] = _required_string(
                        table.get("id"), "table.id"
                    )
            if set(table_ids) == {PAGE_TABLE, QUESTION_TABLE}:
                matches.append((candidate.base_token, table_ids))
        if len(matches) != 1:
            raise intake.SkillError("schema_mismatch", "无法唯一定位错题页面和错题题目表。")
        base_token, table_ids = matches[0]

        tables = {
            name: _TableContext(table_id, self._read_fields(base_token, table_id))
            for name, table_id in table_ids.items()
        }
        _validate_live_schema(tables)
        self._base_token = base_token
        self._tables = tables
        return base_token, tables

    def _read_fields(self, base_token: str, table_id: str) -> dict[str, homework2lark.BaseField]:
        envelope = self.runner.run(
            [
                "base",
                "+field-list",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--as",
                "user",
                "--limit",
                "200",
                "--format",
                "json",
            ],
            retry_read=True,
        )
        raw_fields = _list(_object(envelope.get("data"), "data").get("fields"), "fields")
        fields: dict[str, homework2lark.BaseField] = {}
        for value in raw_fields:
            item = _object(value, "field")
            name = _required_string(item.get("name"), "field.name")
            raw_options = item.get("options")
            options = frozenset(
                _required_string(_object(option, "option").get("name"), "option.name")
                for option in (_list(raw_options, "options") if raw_options is not None else [])
            )
            fields[name] = homework2lark.BaseField(
                _required_string(item.get("id"), "field.id"),
                name,
                _required_string(item.get("type"), "field.type"),
                options,
                item.get("from") if isinstance(item.get("from"), str) else None,
                item.get("select") if isinstance(item.get("select"), str) else None,
            )
        return fields

    def _list_records(
        self,
        base_token: str,
        table: _TableContext,
        fields: Sequence[str],
        *,
        filter_json: dict[str, JSONValue],
    ) -> list[homework2lark.BaseRecord]:
        args = [
            "base",
            "+record-list",
            "--base-token",
            base_token,
            "--table-id",
            table.table_id,
            "--as",
            "user",
            "--limit",
            "2",
        ]
        for name in fields:
            args.extend(("--field-id", name))
        args.extend(("--filter-json", _compact_json(filter_json), "--format", "json"))
        envelope = self.runner.run(args, retry_read=True)
        return homework2lark.parse_columnar_records(_object(envelope.get("data"), "data"))

    def _get_record(
        self,
        base_token: str,
        table: _TableContext,
        record_id: str,
        fields: Sequence[str],
    ) -> homework2lark.BaseRecord:
        args = [
            "base",
            "+record-get",
            "--base-token",
            base_token,
            "--table-id",
            table.table_id,
            "--record-id",
            record_id,
            "--as",
            "user",
        ]
        for name in fields:
            args.extend(("--field-id", name))
        args.extend(("--format", "json"))
        envelope = self.runner.run(args, retry_read=True)
        records = homework2lark.parse_columnar_records(_object(envelope.get("data"), "data"))
        if len(records) != 1:
            raise intake.SkillError("linked_page_not_found", "无法读取题目关联的错题页面。")
        return records[0]

    def _patch(self, table_name: str, record_id: str, patch: dict[str, JSONValue]) -> None:
        base_token, tables = self._context()
        self.runner.run(
            [
                "base",
                "+record-upsert",
                "--base-token",
                base_token,
                "--table-id",
                tables[table_name].table_id,
                "--record-id",
                record_id,
                "--as",
                "user",
                "--json",
                _compact_json(patch),
                "--format",
                "json",
            ]
        )


def _validate_live_schema(tables: dict[str, _TableContext]) -> None:
    expected_page = PAGE_FIELD_TYPES
    expected_question = {
        QUESTION_ID_FIELD: "text",
        QUESTION_PAGE_LINK_FIELD: "link",
        **{name: "lookup" for name in QUESTION_LOOKUP_FIELDS},
        **QUESTION_FIELD_TYPES,
    }
    for table_name, expected in (
        (PAGE_TABLE, expected_page),
        (QUESTION_TABLE, expected_question),
    ):
        fields = tables[table_name].fields
        for name, field_type in expected.items():
            if name not in fields:
                raise intake.SkillError("schema_mismatch", f"Base 缺少字段：{name}。")
            if fields[name].field_type != field_type:
                raise intake.SkillError("schema_mismatch", f"Base 字段类型不匹配：{name}。")
    page_source_options = tables[PAGE_TABLE].fields["错题来源"].options
    if not intake.PAGE_SOURCE_OPTIONS.issubset(page_source_options):
        raise intake.SkillError("schema_mismatch", "错题来源缺少约定选项。")
    grade_options = tables[PAGE_TABLE].fields["年级"].options
    if grade_options != intake.GRADE_OPTIONS:
        raise intake.SkillError("schema_mismatch", "年级选项与约定不一致。")
    page_fields = tables[PAGE_TABLE].fields
    page_table_id = tables[PAGE_TABLE].table_id
    for lookup_name, source_name in QUESTION_LOOKUP_FIELDS.items():
        lookup = tables[QUESTION_TABLE].fields[lookup_name]
        source = page_fields[source_name]
        if lookup.source_table not in {PAGE_TABLE, page_table_id}:
            raise intake.SkillError("schema_mismatch", f"查找引用来源表不匹配：{lookup_name}。")
        if lookup.selected_field not in {source_name, source.field_id}:
            raise intake.SkillError("schema_mismatch", f"查找引用来源字段不匹配：{lookup_name}。")
    question_type_options = tables[QUESTION_TABLE].fields["题型"].options
    if not intake.QUESTION_TYPE_OPTIONS.issubset(question_type_options):
        raise intake.SkillError("schema_mismatch", "题型缺少约定选项。")
    core_options = tables[QUESTION_TABLE].fields["核心素养"].options
    if core_options != intake.CORE_LITERACY_OPTIONS:
        raise intake.SkillError("schema_mismatch", "核心素养选项与约定不一致。")


def _plan_fields(current: dict[str, JSONValue], proposed: dict[str, JSONValue]) -> FieldPlan:
    patch: dict[str, JSONValue] = {}
    unchanged: list[str] = []
    conflicts: list[str] = []
    for name, value in proposed.items():
        normalized_current = _normalized_cell(current.get(name))
        normalized_value = _normalized_cell(value)
        if _empty(normalized_current) or _replaceable_catalog_title(name, normalized_current):
            patch[name] = value
        elif normalized_current == normalized_value:
            unchanged.append(name)
        else:
            conflicts.append(name)
    return FieldPlan(
        patch=patch,
        unchanged=tuple(sorted(unchanged)),
        conflicts=tuple(sorted(conflicts)),
    )


def _replaceable_catalog_title(name: str, value: JSONValue) -> bool:
    if name not in {"页面名称", "题目名称"} or not isinstance(value, str):
        return False
    normalized = value.strip()
    return (
        normalized.isdigit()
        or normalized.startswith("待整理页面·")
        or normalized.startswith("待整理题目·")
    )


def _validate_linked_lookup_values(rows: EnrichmentRows) -> None:
    for lookup_name, page_name in QUESTION_LOOKUP_FIELDS.items():
        if _normalized_cell(rows.question.fields.get(lookup_name)) != _normalized_cell(
            rows.page.fields.get(page_name)
        ):
            raise intake.SkillError(
                "schema_mismatch",
                f"题目查找引用与所属页面不一致：{lookup_name}。",
            )


def _verify_patch(current: dict[str, JSONValue], patch: dict[str, JSONValue]) -> None:
    mismatched = [
        name
        for name, expected in patch.items()
        if _normalized_cell(current.get(name)) != _normalized_cell(expected)
    ]
    if mismatched:
        raise intake.SkillError(
            "metadata_readback_mismatch",
            "Base 写入后的读回结果不一致，请停止后续操作并人工检查。",
            retryable=True,
        )


def _public_field_plan(plan: FieldPlan) -> dict[str, JSONValue]:
    return {
        "willWrite": sorted(plan.patch),
        "unchanged": list(plan.unchanged),
        "conflicts": list(plan.conflicts),
    }


def _normalized_cell(value: JSONValue) -> JSONValue:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0].strip()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return sorted(item.strip() for item in value)
    return value


def _empty(value: JSONValue) -> bool:
    return value is None or value == "" or value == []


def _single_link_id(value: JSONValue) -> str:
    links = _list(value, QUESTION_PAGE_LINK_FIELD)
    if len(links) != 1:
        raise intake.SkillError("linked_page_invalid", "题目必须且只能关联一个错题页面。")
    return _required_string(_object(links[0], "page link").get("id"), "page link.id")


def _object(value: JSONValue, label: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise intake.SkillError("invalid_payload", f"{label} 必须是对象。")
    return value


def _list(value: JSONValue, label: str) -> list[JSONValue]:
    if not isinstance(value, list):
        raise intake.SkillError("invalid_payload", f"{label} 必须是数组。")
    return value


def _required_string(value: JSONValue, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise intake.SkillError("invalid_payload", f"{label} 必须是非空文本。")
    return value


def _compact_json(value: JSONValue | dict[str, JSONValue]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely enrich corrected Base records")
    parser.add_argument(
        "--base-title",
        default=os.environ.get("SHI_HOMEWORK2LARK_BASE_TITLE", DEFAULT_BASE_TITLE),
    )
    parser.add_argument(
        "--lark-cli-command", default=os.environ.get("LARK_CLI_COMMAND", "lark-cli")
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "apply"):
        child = commands.add_parser(command)
        child.add_argument("--input", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = BaseMetadataService(
        LarkMetadataGateway(
            homework2lark.SubprocessRunner(args.lark_cli_command),
            base_title=args.base_title,
        )
    )
    try:
        payload = intake._load_json(args.input)
        if args.command == "preview":
            result: JSONValue = service.preview(payload).public()
        elif args.command == "apply":
            result = service.apply(payload)
        else:
            raise intake.SkillError("unsupported_command", "不支持的命令。")
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except (intake.SkillError, homework2lark.SkillError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "retryable": exc.retryable,
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
