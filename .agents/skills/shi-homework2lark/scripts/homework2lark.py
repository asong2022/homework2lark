#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

DEFAULT_BASE_TITLE = "小学数学错题学习库"
DEFAULT_TABLE_NAME = "错题题目"
TABLE_NAME_ALIASES = ("错题题目", "questions")
QUESTION_ID_FIELDS = ("系统题目ID", "题目唯一ID")
SELECTED_VIEW = "待生成变式"
AVAILABLE_VIEW = "已有变式"
TYPICAL_ERROR_FIELD = "典型错例"
ERROR_PATTERN_FIELD = "错误表现"
ERROR_CAUSE_SUMMARY_FIELD = "错误原因"
COLLECTION_ORDER_FIELD = "收录序号"
MANUAL_ATTENTION_FIELD = "需人工处理"
REVERSE_VARIANT_LINK_FIELD = "关联变式题"
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
READ_FIELDS_WITHOUT_ID = (
    "题目名称",
    COLLECTION_ORDER_FIELD,
    "图片题目",
    "题干图片",
    "题干文本",
    "标准答案",
    "核心素养",
    "对应知识点",
    "设计意图",
    TYPICAL_ERROR_FIELD,
    ERROR_PATTERN_FIELD,
    ERROR_CAUSE_SUMMARY_FIELD,
    "时间",
    "年级",
    "页码",
    "错题来源",
    "本地修订版本",
    MANUAL_ATTENTION_FIELD,
    REVERSE_VARIANT_LINK_FIELD,
)

EXPECTED_FIELD_TYPES = {
    MANUAL_ATTENTION_FIELD: "checkbox",
    REVERSE_VARIANT_LINK_FIELD: "link",
}
EXPECTED_SOURCE_LOOKUPS = {
    "时间": "lookup",
    "年级": "lookup",
    "页码": "lookup",
    "错题来源": "lookup",
    TYPICAL_ERROR_FIELD: "lookup",
    ERROR_PATTERN_FIELD: "lookup",
}
EXPECTED_SOURCE_FIELD_TYPES = {
    "题目名称": "text",
    COLLECTION_ORDER_FIELD: "auto_number",
    "题干图片": "attachment",
    "核心素养": "select",
    "设计意图": "text",
    ERROR_CAUSE_SUMMARY_FIELD: "text",
    "本地修订版本": "number",
}
EXPECTED_VIEW_FILTERS: dict[str, tuple[tuple[JSONValue, ...], ...]] = {
    SELECTED_VIEW: (
        (REVERSE_VARIANT_LINK_FIELD, "empty"),
        (MANUAL_ATTENTION_FIELD, "==", False),
    ),
    AVAILABLE_VIEW: (
        (REVERSE_VARIANT_LINK_FIELD, "non_empty"),
        (MANUAL_ATTENTION_FIELD, "==", False),
    ),
}


class SkillError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        upstream_code: int | None = None,
        upstream_type: str | None = None,
        upstream_subtype: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.upstream_code = upstream_code
        self.upstream_type = upstream_type
        self.upstream_subtype = upstream_subtype


@dataclass(frozen=True)
class BaseField:
    field_id: str
    name: str
    field_type: str
    options: frozenset[str]
    source_table: str | None = None
    selected_field: str | None = None


@dataclass(frozen=True)
class BaseView:
    view_id: str
    name: str


@dataclass(frozen=True)
class BaseSchema:
    fields: dict[str, BaseField]
    views: dict[str, BaseView]
    filters: dict[str, dict[str, JSONValue]]


@dataclass(frozen=True)
class ResolvedBaseCandidate:
    base_token: str
    tables: tuple[dict[str, JSONValue], ...]


@dataclass(frozen=True)
class BaseRecord:
    record_id: str
    fields: dict[str, JSONValue]


@dataclass(frozen=True)
class DiagramArtifact:
    required: bool
    description: str
    local_png: str | None = None
    editable_html: str | None = None


@dataclass(frozen=True)
class Variant:
    question: str
    answer_analysis: str | None
    design_intent: str
    diagram: DiagramArtifact | None = None


@dataclass(frozen=True)
class GeneratedPayload:
    question_id: str
    variants: tuple[Variant, ...]


class CommandRunner(Protocol):
    def run(self, args: Sequence[str], *, retry_read: bool = False) -> dict[str, JSONValue]: ...


class Gateway(Protocol):
    def schema(self) -> BaseSchema: ...

    def list_records(
        self,
        fields: Sequence[str],
        *,
        view_id: str | None = None,
        filter_json: dict[str, JSONValue] | None = None,
        limit: int = 200,
    ) -> list[BaseRecord]: ...

    def get_record(self, record_id: str, fields: Sequence[str]) -> BaseRecord: ...

    def patch_record(self, record_id: str, patch: dict[str, JSONValue]) -> None: ...

    def download_attachments(self, record_id: str, output_dir: str) -> None: ...

    def upload_attachment(self, record_id: str, field_name: str, file_path: str) -> None: ...


class SubprocessRunner:
    def __init__(self, command: str = "lark-cli") -> None:
        self.command = shutil.which(command) or command

    def run(self, args: Sequence[str], *, retry_read: bool = False) -> dict[str, JSONValue]:
        attempts = 3 if retry_read else 1
        for attempt in range(attempts):
            envelope, return_code = self._run_once(args)
            if return_code == 0 and envelope.get("ok") is True:
                return envelope

            error = envelope.get("error")
            error_object = error if isinstance(error, dict) else {}
            raw_code = error_object.get("code")
            numeric_code = raw_code if isinstance(raw_code, int) else None
            upstream_type = (
                error_object.get("type") if isinstance(error_object.get("type"), str) else None
            )
            upstream_subtype = (
                error_object.get("subtype")
                if isinstance(error_object.get("subtype"), str)
                else None
            )
            raw_message = error_object.get("message")
            argument_split = (
                isinstance(raw_message, str)
                and "positional arguments are not supported" in raw_message.lower()
            )
            if retry_read and numeric_code in {9499, 1254291} and attempt + 1 < attempts:
                time.sleep(attempt + 1)
                continue
            if argument_split:
                raise SkillError(
                    "lark_cli_argument_split",
                    "Windows lark-cli 包装器拆分了长 JSON 参数。",
                    upstream_type=upstream_type,
                    upstream_subtype=upstream_subtype,
                )
            raise _safe_cli_error(numeric_code, upstream_type, upstream_subtype)
        raise SkillError("lark_unavailable", "飞书暂时不可用，请稍后重试。", retryable=True)

    def _run_once(self, args: Sequence[str]) -> tuple[dict[str, JSONValue], int]:
        environment = os.environ.copy()
        environment["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        environment["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        try:
            completed = subprocess.run(
                [self.command, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise SkillError(
                "lark_cli_missing", "未找到 lark-cli，请先安装并完成用户登录。"
            ) from exc

        raw = completed.stdout if completed.returncode == 0 else completed.stderr
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SkillError(
                "lark_invalid_response", "飞书返回无法解析，请检查 lark-cli 状态。"
            ) from exc
        if not isinstance(decoded, dict):
            raise SkillError("lark_invalid_response", "飞书返回结构不正确。")
        return decoded, completed.returncode


def _safe_cli_error(
    code: int | None, upstream_type: str | None, upstream_subtype: str | None
) -> SkillError:
    context = {"upstream_type": upstream_type, "upstream_subtype": upstream_subtype}
    if code == 800070003:
        return SkillError("lark_no_change", "飞书记录已是目标状态。", upstream_code=code, **context)
    if code in {9499, 1254291}:
        return SkillError(
            "lark_rate_limited",
            "飞书请求过于频繁，请稍后重试。",
            retryable=True,
            upstream_code=code,
            **context,
        )
    if code in {91403, 99991679}:
        return SkillError(
            "lark_permission_denied",
            "飞书用户身份缺少访问权限，请恢复授权后重试。",
            upstream_code=code,
            **context,
        )
    return SkillError(
        "lark_operation_failed",
        "飞书操作失败，请检查 Base 结构和登录状态。",
        retryable=True,
        upstream_code=code,
        **context,
    )


def resolve_base_candidates(
    runner: CommandRunner, base_title: str
) -> tuple[ResolvedBaseCandidate, ...]:
    """Resolve every accessible exact-title Base candidate and read its tables.

    Feishu may return both the direct Base and an app wrapper for one visible title.
    Callers must select the unique candidate whose table schema matches their contract.
    """

    resolved = runner.run(
        [
            "base",
            "+title-resolve",
            "--title",
            base_title[:30],
            "--as",
            "user",
            "--format",
            "json",
        ],
        retry_read=True,
    )
    data = _require_object(resolved, "data")
    if isinstance(data.get("base_token"), str):
        raw_candidates: list[JSONValue] = [data]
    else:
        raw_candidates = _require_list(data, "candidates")

    candidates = [_as_object(value, "Base 候选") for value in raw_candidates]
    exact_title = [candidate for candidate in candidates if candidate.get("title") == base_title]
    if exact_title:
        candidates = exact_title

    resolved_candidates: list[ResolvedBaseCandidate] = []
    failures: list[SkillError] = []
    seen_tokens: set[str] = set()
    for candidate in candidates:
        token = candidate.get("base_token")
        if not isinstance(token, str) or not token or token in seen_tokens:
            continue
        seen_tokens.add(token)
        try:
            tables_envelope = runner.run(
                [
                    "base",
                    "+table-list",
                    "--base-token",
                    token,
                    "--as",
                    "user",
                    "--limit",
                    "100",
                    "--format",
                    "json",
                ],
                retry_read=True,
            )
        except SkillError as exc:
            failures.append(exc)
            continue
        tables = tuple(
            _as_object(value, "数据表")
            for value in _require_list(_require_object(tables_envelope, "data"), "tables")
        )
        resolved_candidates.append(ResolvedBaseCandidate(token, tables))

    if not resolved_candidates:
        if failures:
            raise failures[0]
        raise SkillError("schema_mismatch", "没有找到可访问的同名飞书 Base。")
    return tuple(resolved_candidates)


class LarkCliGateway:
    def __init__(
        self,
        runner: CommandRunner,
        *,
        base_title: str = DEFAULT_BASE_TITLE,
        table_name: str = DEFAULT_TABLE_NAME,
    ) -> None:
        self.runner = runner
        self.base_title = base_title
        self.table_name = table_name
        self._base_token: str | None = None
        self._table_id: str | None = None
        self._resolved_table_name: str | None = None
        self._schema: BaseSchema | None = None

    @property
    def resolved_table_name(self) -> str:
        self._context()
        if self._resolved_table_name is None:
            raise SkillError("schema_mismatch", "无法确定错题题目数据表名称。")
        return self._resolved_table_name

    def schema(self) -> BaseSchema:
        if self._schema is not None:
            return self._schema
        base_token, table_id = self._context()
        field_envelope = self.runner.run(
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
                "--json",
            ],
            retry_read=True,
        )
        field_items = _require_list(_require_object(field_envelope, "data"), "fields")
        fields: dict[str, BaseField] = {}
        field_id_to_name: dict[str, str] = {}
        for raw_field in field_items:
            item = _as_object(raw_field, "字段")
            field_id = _require_string(item, "id")
            name = _require_string(item, "name")
            field_type = _require_string(item, "type")
            raw_options = item.get("options")
            options: set[str] = set()
            if isinstance(raw_options, list):
                for raw_option in raw_options:
                    if isinstance(raw_option, dict) and isinstance(raw_option.get("name"), str):
                        options.add(raw_option["name"])
            source_table = item.get("from") if isinstance(item.get("from"), str) else None
            selected_field = item.get("select") if isinstance(item.get("select"), str) else None
            fields[name] = BaseField(
                field_id,
                name,
                field_type,
                frozenset(options),
                source_table,
                selected_field,
            )
            field_id_to_name[field_id] = name

        view_envelope = self.runner.run(
            [
                "base",
                "+view-list",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--as",
                "user",
                "--limit",
                "200",
                "--json",
            ],
            retry_read=True,
        )
        view_items = _require_list(_require_object(view_envelope, "data"), "views")
        views: dict[str, BaseView] = {}
        for raw_view in view_items:
            item = _as_object(raw_view, "视图")
            view = BaseView(_require_string(item, "id"), _require_string(item, "name"))
            views[view.name] = view

        filters: dict[str, dict[str, JSONValue]] = {}
        for view_name in EXPECTED_VIEW_FILTERS:
            view = views.get(view_name)
            if view is None:
                continue
            filter_envelope = self.runner.run(
                [
                    "base",
                    "+view-get-filter",
                    "--base-token",
                    base_token,
                    "--table-id",
                    table_id,
                    "--view-id",
                    view.view_id,
                    "--as",
                    "user",
                    "--json",
                ],
                retry_read=True,
            )
            filter_data = _require_object(filter_envelope, "data")
            filter_object = _as_object(filter_data.get("filter"), "视图筛选")
            filters[view_name] = _normalize_filter_fields(filter_object, field_id_to_name)

        self._schema = BaseSchema(fields=fields, views=views, filters=filters)
        return self._schema

    def list_records(
        self,
        fields: Sequence[str],
        *,
        view_id: str | None = None,
        filter_json: dict[str, JSONValue] | None = None,
        limit: int = 200,
    ) -> list[BaseRecord]:
        base_token, table_id = self._context()
        args = [
            "base",
            "+record-list",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--as",
            "user",
            "--limit",
            str(limit),
        ]
        for field_name in fields:
            args.extend(("--field-id", field_name))
        if view_id is not None:
            args.extend(("--view-id", view_id))
        if filter_json is not None:
            args.extend(("--filter-json", _compact_json(filter_json)))
        args.extend(("--format", "json"))
        envelope = self.runner.run(args, retry_read=True)
        data = _require_object(envelope, "data")
        if data.get("has_more") is True:
            raise SkillError("result_too_large", "目标范围超过 200 条，请缩小视图或筛选范围。")
        return parse_columnar_records(data)

    def get_record(self, record_id: str, fields: Sequence[str]) -> BaseRecord:
        base_token, table_id = self._context()
        args = [
            "base",
            "+record-get",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--record-id",
            record_id,
            "--as",
            "user",
        ]
        # The Windows CLI parser rejects very large repeated projections. Full-row
        # snapshots are both shorter on argv and required for source-field protection.
        if len(fields) <= 20:
            for field_name in fields:
                args.extend(("--field-id", field_name))
        args.extend(("--format", "json"))
        envelope = self.runner.run(args, retry_read=True)
        records = parse_columnar_records(_require_object(envelope, "data"))
        if len(records) != 1:
            raise SkillError("record_not_found", "没有找到指定题目记录。")
        return records[0]

    def patch_record(self, record_id: str, patch: dict[str, JSONValue]) -> None:
        base_token, table_id = self._context()
        try:
            self.runner.run(
                [
                    "base",
                    "+record-upsert",
                    "--base-token",
                    base_token,
                    "--table-id",
                    table_id,
                    "--record-id",
                    record_id,
                    "--as",
                    "user",
                    "--json",
                    _compact_json(patch),
                ]
            )
        except SkillError as exc:
            if exc.code != "lark_no_change":
                raise

    def download_attachments(self, record_id: str, output_dir: str) -> None:
        base_token, table_id = self._context()
        self.runner.run(
            [
                "base",
                "+record-download-attachment",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--record-id",
                record_id,
                "--output",
                output_dir,
                "--as",
                "user",
                "--json",
            ],
            retry_read=True,
        )

    def upload_attachment(self, record_id: str, field_name: str, file_path: str) -> None:
        base_token, table_id = self._context()
        schema = self.schema()
        field = schema.fields.get(field_name)
        if field is None or field.field_type != "attachment":
            raise SkillError("schema_mismatch", f"Base 题图附件字段无效：{field_name}。")
        self.runner.run(
            [
                "base",
                "+record-upload-attachment",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--record-id",
                record_id,
                "--field-id",
                field.field_id,
                "--file",
                file_path,
                "--as",
                "user",
                "--format",
                "json",
            ]
        )

    def _context(self) -> tuple[str, str]:
        if self._base_token is not None and self._table_id is not None:
            return self._base_token, self._table_id
        accepted_names = (
            TABLE_NAME_ALIASES if self.table_name in TABLE_NAME_ALIASES else (self.table_name,)
        )
        contexts: list[tuple[str, dict[str, JSONValue]]] = []
        for candidate in resolve_base_candidates(self.runner, self.base_title):
            matches = [table for table in candidate.tables if table.get("name") in accepted_names]
            if len(matches) == 1:
                contexts.append((candidate.base_token, matches[0]))
        if len(contexts) != 1:
            raise SkillError("schema_mismatch", "无法唯一定位错题题目数据表。")
        base_token, table = contexts[0]
        self._base_token = base_token
        self._table_id = _require_string(table, "id")
        self._resolved_table_name = _require_string(table, "name")
        return self._base_token, self._table_id


class Homework2LarkService:
    def __init__(self, gateway: Gateway, *, clock: Callable[[], datetime] | None = None) -> None:
        self.gateway = gateway
        self.clock = clock or (lambda: datetime.now().astimezone())

    def schema_check(self) -> dict[str, JSONValue]:
        schema = self.gateway.schema()
        validate_schema(schema)
        return {
            "table": (
                self.gateway.resolved_table_name
                if isinstance(self.gateway, LarkCliGateway)
                else DEFAULT_TABLE_NAME
            ),
            "generatedFieldCount": len(EXPECTED_FIELD_TYPES),
            "requiredViews": list(EXPECTED_VIEW_FILTERS),
            "exceptionField": MANUAL_ATTENTION_FIELD,
        }

    def list_selected(self) -> list[dict[str, JSONValue]]:
        schema = self._validated_schema()
        records = self.gateway.list_records(
            read_fields(schema), view_id=schema.views[SELECTED_VIEW].view_id
        )
        for record in records:
            ensure_source_eligible(record)
            if not _empty(record.fields.get(REVERSE_VARIANT_LINK_FIELD)):
                raise SkillError(
                    "view_filter_drift", "待生成视图包含已有变式的记录，请先修复视图筛选。"
                )
        return [public_record(record) for record in records]

    def get(self, *, question_id: str | None, record_id: str | None) -> dict[str, JSONValue]:
        schema = self._validated_schema()
        if record_id is not None:
            record = self.gateway.get_record(record_id, read_fields(schema))
        else:
            assert question_id is not None
            question_field = schema.fields[question_id_field(schema)].field_id
            records = self.gateway.list_records(
                read_fields(schema),
                filter_json={
                    "logic": "and",
                    "conditions": [[question_field, "==", question_id]],
                },
                limit=2,
            )
            if len(records) == 0:
                raise SkillError("record_not_found", "没有找到指定题目记录。")
            if len(records) > 1:
                raise SkillError("duplicate_question_id", "系统题目ID存在重复记录，请先清理冲突。")
            record = records[0]
        ensure_source_eligible(record)
        return public_record(record)

    def write(
        self, record_id: str, payload: GeneratedPayload, *, replace_all: bool
    ) -> dict[str, JSONValue]:
        del record_id, payload, replace_all
        raise SkillError(
            "independent_variant_catalog_required",
            "原题同行变式列已删除；请使用 variant_catalog.py write 写入独立变式题表。",
        )

    def attach_diagram(
        self, record_id: str, variant_number: int, file_path: str
    ) -> dict[str, JSONValue]:
        del record_id, variant_number, file_path
        raise SkillError(
            "independent_variant_catalog_required",
            "请通过 variant_catalog.py write 将题图上传到独立变式题记录。",
        )

    def list_available(self) -> list[dict[str, JSONValue]]:
        raise SkillError(
            "independent_variant_catalog_required",
            "请使用 variant_catalog.py list-available 读取独立变式题表。",
        )

    def download_images(self, record_id: str, output_dir: str) -> dict[str, JSONValue]:
        self._validated_schema()
        relative = validate_relative_directory(output_dir)
        self.gateway.download_attachments(record_id, relative)
        return {"recordId": record_id, "outputDir": relative}

    def _validated_schema(self) -> BaseSchema:
        schema = self.gateway.schema()
        validate_schema(schema)
        return schema

    @staticmethod
    def _verify_source_unchanged(source_snapshot: dict[str, JSONValue], after: BaseRecord) -> None:
        for name, expected in source_snapshot.items():
            if not _json_equal(after.fields.get(name), expected):
                raise SkillError(
                    "source_changed", "原题字段在写回过程中发生变化，请停止并人工检查。"
                )


def validate_schema(schema: BaseSchema) -> None:
    for name, expected_type in EXPECTED_FIELD_TYPES.items():
        field = schema.fields.get(name)
        if field is None:
            raise SkillError("schema_mismatch", f"Base 缺少字段：{name}。")
        if field.field_type != expected_type:
            raise SkillError("schema_mismatch", f"Base 字段类型不匹配：{name}。")
    question_id_field(schema)
    for name, expected_type in EXPECTED_SOURCE_LOOKUPS.items():
        field = schema.fields.get(name)
        if field is None or field.field_type != expected_type:
            raise SkillError("schema_mismatch", f"Base 来源字段必须是查找引用：{name}。")
    for name, expected_type in EXPECTED_SOURCE_FIELD_TYPES.items():
        field = schema.fields.get(name)
        if field is None or field.field_type != expected_type:
            raise SkillError("schema_mismatch", f"Base 原题辅助字段类型不匹配：{name}。")
    if schema.fields["核心素养"].options != CORE_LITERACY_OPTIONS:
        raise SkillError("schema_mismatch", "核心素养选项与约定不一致。")
    for required_source in (
        "题干文本",
        "图片题目",
        MANUAL_ATTENTION_FIELD,
    ):
        if required_source not in schema.fields:
            raise SkillError("schema_mismatch", f"Base 缺少原题字段：{required_source}。")
    for view_name, expected_conditions in EXPECTED_VIEW_FILTERS.items():
        if view_name not in schema.views or view_name not in schema.filters:
            raise SkillError("schema_mismatch", f"Base 缺少或无法读取视图：{view_name}。")
        actual_filter = schema.filters[view_name]
        if actual_filter.get("logic") != "and":
            raise SkillError("schema_mismatch", f"视图筛选逻辑必须为 and：{view_name}。")
        raw_conditions = actual_filter.get("conditions")
        if not isinstance(raw_conditions, list):
            raise SkillError("schema_mismatch", f"视图筛选条件无效：{view_name}。")
        actual = {_condition_signature(condition) for condition in raw_conditions}
        expected = {_condition_signature(list(condition)) for condition in expected_conditions}
        if not expected.issubset(actual):
            raise SkillError("schema_mismatch", f"视图筛选条件不完整：{view_name}。")


def question_id_field(schema: BaseSchema) -> str:
    for name in QUESTION_ID_FIELDS:
        field = schema.fields.get(name)
        if field is not None:
            if field.field_type != "text":
                raise SkillError("schema_mismatch", f"Base 字段类型不匹配：{name}。")
            return name
    raise SkillError("schema_mismatch", "Base 缺少系统题目ID。")


def read_fields(schema: BaseSchema) -> tuple[str, ...]:
    return (
        question_id_field(schema),
        *(name for name in READ_FIELDS_WITHOUT_ID if name in schema.fields),
    )


def question_id(record: BaseRecord) -> str:
    target = _text(record.fields.get("系统题目ID"))
    legacy = _text(record.fields.get("题目唯一ID"))
    if target and legacy and target != legacy:
        raise SkillError("source_incomplete", "系统题目 ID 与旧题目 ID 不一致。")
    return target or legacy


def validate_generated_payload(raw: JSONValue) -> GeneratedPayload:
    obj = _as_object(raw, "生成结果")
    allowed = {"questionId", "variants"}
    unknown = set(obj) - allowed
    if unknown:
        raise SkillError("invalid_payload", "生成结果包含未支持的字段。")
    question_id = _require_nonempty_text(obj.get("questionId"), "questionId", maximum=120)
    if not question_id.startswith("problem_"):
        raise SkillError("invalid_payload", "questionId 必须是本地 problem_ 稳定 ID。")
    raw_variants = obj.get("variants")
    if not isinstance(raw_variants, list) or not 1 <= len(raw_variants) <= 5:
        raise SkillError("invalid_payload", "variants 必须包含 1～5 道变式题。")
    variants: list[Variant] = []
    normalized_questions: set[str] = set()
    for raw_variant in raw_variants:
        variant = _as_object(raw_variant, "变式题")
        allowed_variant = {"question", "answerAnalysis", "designIntent", "diagram"}
        if set(variant) - allowed_variant or "question" not in variant:
            raise SkillError(
                "invalid_payload",
                "每道变式题必须包含 question 和 designIntent，"
                "只能另含可选 answerAnalysis 和 diagram。",
            )
        design_intent = _require_nonempty_text(
            variant.get("designIntent"), "designIntent", maximum=5_000
        )
        question = _require_nonempty_text(variant.get("question"), "question", maximum=20_000)
        normalized_question = " ".join(question.split())
        if normalized_question in normalized_questions:
            raise SkillError("duplicate_variant", "同一次写入不能包含重复的变式题题干。")
        normalized_questions.add(normalized_question)
        diagram = validate_diagram_artifact(variant.get("diagram"))
        variants.append(
            Variant(
                question,
                _optional_text(variant.get("answerAnalysis"), "answerAnalysis", maximum=20_000),
                design_intent,
                diagram,
            )
        )
    return GeneratedPayload(question_id, tuple(variants))


def ensure_source_eligible(record: BaseRecord, *, allow_attention: bool = False) -> None:
    if record.fields.get(MANUAL_ATTENTION_FIELD) is True and not allow_attention:
        raise SkillError("source_needs_attention", "该题已标记为需人工处理，请先解决异常。")
    if not question_id(record):
        raise SkillError("source_incomplete", "原题缺少稳定题目 ID。")
    revision_number = record.fields.get("本地修订版本")
    if (
        isinstance(revision_number, bool)
        or not isinstance(revision_number, (int, float))
        or revision_number < 1
        or revision_number % 1 != 0
    ):
        raise SkillError(
            "source_revision_missing",
            "原题缺少有效的本地修订版本，不能生成变式题。",
        )
    has_text = bool(_text(record.fields.get("题干文本")))
    has_image = _attachment_count(record.fields.get("图片题目")) > 0
    if not has_text and not has_image:
        raise SkillError("source_incomplete", "原题既没有完整文本，也没有题目图片。")


def stored_variants(record: BaseRecord) -> tuple[Variant, ...]:
    del record
    raise SkillError(
        "independent_variant_catalog_required",
        "同行变式列已删除；请从独立变式题表读取。",
    )


def public_record(record: BaseRecord) -> dict[str, JSONValue]:
    linked_variants = record.fields.get(REVERSE_VARIANT_LINK_FIELD)
    populated = len(linked_variants) if isinstance(linked_variants, list) else 0
    needs_attention = record.fields.get(MANUAL_ATTENTION_FIELD) is True
    status = "需人工处理" if needs_attention else "可用" if populated else "未生成"
    return {
        "recordId": record.record_id,
        "questionId": question_id(record),
        "collectionOrder": _text(record.fields.get(COLLECTION_ORDER_FIELD)),
        "questionText": _text(record.fields.get("题干文本")),
        "questionImageCount": _attachment_count(record.fields.get("图片题目")),
        "questionStemImageCount": _attachment_count(record.fields.get("题干图片")),
        "standardAnswer": _text(record.fields.get("标准答案")),
        "coreLiteracy": _select_values(record.fields.get("核心素养")),
        "knowledgePoints": _text(record.fields.get("对应知识点")),
        "designIntent": _text(record.fields.get("设计意图")),
        "typicalStudentError": _text(record.fields.get(TYPICAL_ERROR_FIELD)),
        "errorPattern": _text(record.fields.get(ERROR_PATTERN_FIELD)),
        "errorCauseSummary": _text(record.fields.get(ERROR_CAUSE_SUMMARY_FIELD)),
        "pageNumber": _text(record.fields.get("页码")),
        "mistakeSource": _text(record.fields.get("错题来源")),
        "generationStatus": status,
        "needsManualAttention": needs_attention,
        "selected": populated == 0 and not needs_attention,
        "storedVariantCount": populated,
        "diagramRequiredCount": 0,
        "diagramReadyCount": 0,
    }


def parse_columnar_records(data: dict[str, JSONValue]) -> list[BaseRecord]:
    fields = _require_list(data, "fields")
    rows = _require_list(data, "data")
    record_ids = _require_list(data, "record_id_list")
    field_names = [value for value in fields if isinstance(value, str)]
    if len(field_names) != len(fields) or len(rows) != len(record_ids):
        raise SkillError("lark_invalid_response", "飞书列式记录返回不完整。")
    records: list[BaseRecord] = []
    for row_index, raw_row in enumerate(rows):
        if not isinstance(raw_row, list) or len(raw_row) != len(field_names):
            raise SkillError("lark_invalid_response", "飞书记录列数与字段数不一致。")
        record_id = record_ids[row_index]
        if not isinstance(record_id, str) or not record_id:
            raise SkillError("lark_invalid_response", "飞书记录缺少 record ID。")
        records.append(BaseRecord(record_id, dict(zip(field_names, raw_row, strict=True))))
    return records


def _normalize_filter_fields(
    filter_object: dict[str, JSONValue], field_id_to_name: dict[str, str]
) -> dict[str, JSONValue]:
    raw_conditions = filter_object.get("conditions")
    if not isinstance(raw_conditions, list):
        return filter_object
    conditions: list[JSONValue] = []
    for raw_condition in raw_conditions:
        if not isinstance(raw_condition, list) or len(raw_condition) < 2:
            conditions.append(raw_condition)
            continue
        normalized = list(raw_condition)
        if isinstance(normalized[0], str):
            normalized[0] = field_id_to_name.get(normalized[0], normalized[0])
        conditions.append(normalized)
    return {"logic": filter_object.get("logic", "and"), "conditions": conditions}


def _condition_signature(value: JSONValue) -> str:
    if not isinstance(value, list) or len(value) < 2:
        return _compact_json(value)
    if value[1] in {"empty", "non_empty"}:
        return _compact_json(value[:2])
    return _compact_json(value)


def load_json_input(path_value: str) -> JSONValue:
    if path_value == "-":
        content = sys.stdin.read()
    else:
        resolved = Path(path_value).expanduser().resolve()
        try:
            content = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillError("input_unreadable", "无法读取生成结果文件。") from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise SkillError("invalid_payload", "生成结果不是有效 JSON。") from exc


def validate_relative_directory(path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts:
        raise SkillError("unsafe_path", "附件输出目录必须是当前目录内的相对路径。")
    resolved = (Path.cwd() / path).resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise SkillError("unsafe_path", "附件输出目录超出当前工作目录。")
    resolved.mkdir(parents=True, exist_ok=True)
    return str(path).replace("\\", "/")


def validate_relative_file(path_value: str, *, extensions: set[str]) -> tuple[str, Path]:
    path = Path(path_value).expanduser()
    resolved = path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()
    if resolved.suffix.lower() not in extensions or not resolved.is_file():
        raise SkillError("artifact_unreadable", "题图文件不存在或格式不受支持。")
    return str(resolved), resolved


def validate_diagram_artifact(value: JSONValue) -> DiagramArtifact | None:
    if value is None:
        return None
    diagram = _as_object(value, "diagram")
    if set(diagram) != {"required", "description", "localPng", "editableHtml"}:
        raise SkillError(
            "invalid_payload",
            "diagram 必须包含 required、description、localPng 和 editableHtml。",
        )
    if diagram.get("required") is not True:
        raise SkillError("invalid_payload", "提供 diagram 时 required 必须为 true。")
    description = _require_nonempty_text(
        diagram.get("description"), "diagram.description", maximum=2_000
    )
    local_png, _ = validate_relative_file(
        _require_nonempty_text(diagram.get("localPng"), "diagram.localPng", maximum=500),
        extensions={".png", ".jpg", ".jpeg"},
    )
    editable_html, _ = validate_relative_file(
        _require_nonempty_text(diagram.get("editableHtml"), "diagram.editableHtml", maximum=500),
        extensions={".html"},
    )
    return DiagramArtifact(True, description, local_png, editable_html)


def _require_nonempty_text(value: JSONValue, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise SkillError("invalid_payload", f"{name} 必须是非空文本且长度不超过 {maximum}。")
    return value.strip()


def _optional_text(value: JSONValue, name: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum:
        raise SkillError("invalid_payload", f"{name} 必须是长度不超过 {maximum} 的文本。")
    return value.strip() or None


def _require_object(parent: dict[str, JSONValue], key: str) -> dict[str, JSONValue]:
    return _as_object(parent.get(key), key)


def _as_object(value: JSONValue, label: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise SkillError("lark_invalid_response", f"{label}结构无效。")
    return value


def _require_list(parent: dict[str, JSONValue], key: str) -> list[JSONValue]:
    value = parent.get(key)
    if not isinstance(value, list):
        raise SkillError("lark_invalid_response", f"飞书返回缺少 {key} 数组。")
    return value


def _require_string(parent: dict[str, JSONValue], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value:
        raise SkillError("lark_invalid_response", f"飞书返回缺少 {key}。")
    return value


def _text(value: JSONValue) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _select(value: JSONValue) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return ""


def _select_values(value: JSONValue) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                text = item["text"].strip()
                if text:
                    result.append(text)
        return result
    return []


def _attachment_count(value: JSONValue) -> int:
    return len(value) if isinstance(value, list) else 0


def _empty(value: JSONValue) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _json_equal(left: JSONValue, right: JSONValue) -> bool:
    return _compact_json(left) == _compact_json(right)


def _compact_json(value: JSONValue | dict[str, JSONValue]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Feishu Base elementary-math variant workflow")
    parser.add_argument(
        "--base-title",
        default=os.environ.get("SHI_HOMEWORK2LARK_BASE_TITLE", DEFAULT_BASE_TITLE),
    )
    parser.add_argument("--table-name", default=DEFAULT_TABLE_NAME)
    parser.add_argument(
        "--lark-cli-command", default=os.environ.get("LARK_CLI_COMMAND", "lark-cli")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("schema-check")
    subparsers.add_parser("list-selected")

    get_parser = subparsers.add_parser("get")
    get_target = get_parser.add_mutually_exclusive_group(required=True)
    get_target.add_argument("--question-id")
    get_target.add_argument("--record-id")

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--input", required=True)

    write_parser = subparsers.add_parser("write")
    write_parser.add_argument("--record-id", required=True)
    write_parser.add_argument("--input", required=True)
    write_parser.add_argument("--replace-all", action="store_true")

    attach_parser = subparsers.add_parser("attach-diagram")
    attach_parser.add_argument("--record-id", required=True)
    attach_parser.add_argument("--variant", required=True, type=int)
    attach_parser.add_argument("--file", required=True)

    subparsers.add_parser("list-available")

    download_parser = subparsers.add_parser("download-images")
    download_parser.add_argument("--record-id", required=True)
    download_parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            payload = validate_generated_payload(load_json_input(args.input))
            result: JSONValue = {
                "questionId": payload.question_id,
                "variantCount": len(payload.variants),
                "diagramCount": sum(1 for variant in payload.variants if variant.diagram),
                "valid": True,
            }
        else:
            gateway = LarkCliGateway(
                SubprocessRunner(args.lark_cli_command),
                base_title=args.base_title,
                table_name=args.table_name,
            )
            service = Homework2LarkService(gateway)
            if args.command == "schema-check":
                result = service.schema_check()
            elif args.command == "list-selected":
                result = service.list_selected()
            elif args.command == "get":
                result = service.get(question_id=args.question_id, record_id=args.record_id)
            elif args.command == "write":
                payload = validate_generated_payload(load_json_input(args.input))
                result = service.write(args.record_id, payload, replace_all=args.replace_all)
            elif args.command == "attach-diagram":
                result = service.attach_diagram(args.record_id, args.variant, args.file)
            elif args.command == "list-available":
                result = service.list_available()
            elif args.command == "download-images":
                result = service.download_images(args.record_id, args.output_dir)
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
                        **(
                            {"upstreamCode": exc.upstream_code}
                            if exc.upstream_code is not None
                            else {}
                        ),
                        **(
                            {"upstreamType": exc.upstream_type}
                            if exc.upstream_type is not None
                            else {}
                        ),
                        **(
                            {"upstreamSubtype": exc.upstream_subtype}
                            if exc.upstream_subtype is not None
                            else {}
                        ),
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
