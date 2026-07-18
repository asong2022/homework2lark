#!/usr/bin/env python3
"""Validate grouped student-mistake drafts and the live Lark Base schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import homework2lark as core  # noqa: E402

GROUP_TABLE = "错题记录"
QUESTION_TABLE = "错题题目"
STUDENT_TABLE = "学生"

ERROR_CATEGORIES = frozenset(
    (
        "审题与信息提取",
        "概念理解",
        "方法与策略",
        "运算与计算",
        "图形与表征",
        "推理与表达",
        "作答规范",
        "其他/待判断",
    )
)
MASTERY_OPTIONS = frozenset(("未开始", "练习中", "需再练", "已掌握"))
HIGH_FREQUENCY_METHODS = frozenset(("批改统计", "教师判断"))
ACTUAL_RESPONSE_FIELD = "典型错例"
ERROR_PATTERN_FIELD = "错误表现"
ERROR_CAUSE_FIELD = "错误原因"
GROUP_COUNT_FIELD = "本组人数"
QUESTION_IMAGE_LOOKUP_FIELD = "题干图片"
QUESTION_GROUP_LOOKUP_FIELDS = {
    ACTUAL_RESPONSE_FIELD: ACTUAL_RESPONSE_FIELD,
    ERROR_PATTERN_FIELD: ERROR_PATTERN_FIELD,
}
QUESTION_PROJECTION_FIELD_TYPES = {
    "统计批次": "text",
    "批改样本人数": "number",
    "错误人数合计": "number",
    "错误率": "number",
    ERROR_CAUSE_FIELD: "text",
    "是否高频错题": "checkbox",
    "高频判定方式": "select",
}

EXPECTED_FIELD_TYPES = {
    "记录名称": "text",
    "对应学生": "select",
    "对应错题": "link",
    "作业日期": "datetime",
    "错误分类": "select",
    ACTUAL_RESPONSE_FIELD: "text",
    ERROR_PATTERN_FIELD: "text",
    ERROR_CAUSE_FIELD: "text",
    GROUP_COUNT_FIELD: "number",
    QUESTION_IMAGE_LOOKUP_FIELD: "lookup",
    "核心素养": "lookup",
    "掌握状态": "select",
    "再练反馈": "text",
    "最近再练时间": "datetime",
    "系统记录ID": "text",
}


@dataclass(frozen=True)
class FieldState:
    field_id: str
    name: str
    field_type: str
    multiple: bool | None
    options: frozenset[str]
    link_table: str | None
    bidirectional: bool | None
    reverse_field_id: str | None
    number_precision: int | None = None
    number_percentage: bool | None = None
    lookup_from: str | None = None
    lookup_select_field_id: str | None = None


@dataclass(frozen=True)
class GroupSchema:
    table_names: frozenset[str]
    base_token: str
    group_table_id: str
    question_table_id: str
    fields: dict[str, FieldState]
    question_fields: dict[str, FieldState]


@dataclass(frozen=True)
class MistakeGroupDraft:
    question_record_id: str
    question_label: str
    assignment_date: str
    error_category: str
    students: tuple[str, ...]
    actual_response_summary: str
    error_pattern: str
    error_cause: str
    sample_size: int | None

    @property
    def record_name(self) -> str:
        cause = " ".join(self.error_cause.split())
        cause_label = cause[:24] + ("…" if len(cause) > 24 else "")
        return f"{self.assignment_date}｜{self.question_label}｜{cause_label}"

    @property
    def system_record_id(self) -> str:
        identity = {
            "questionRecordId": self.question_record_id,
            "assignmentDate": self.assignment_date,
            "errorCategory": self.error_category,
            "errorCause": " ".join(self.error_cause.split()),
        }
        encoded = json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "mistake_group_" + hashlib.sha256(encoded).hexdigest()[:24]

    def base_fields(self) -> dict[str, core.JSONValue]:
        values: dict[str, core.JSONValue] = {
            "记录名称": self.record_name,
            "对应学生": list(self.students),
            "对应错题": [{"id": self.question_record_id}],
            "作业日期": f"{self.assignment_date} 00:00:00",
            "错误分类": self.error_category,
            ACTUAL_RESPONSE_FIELD: self.actual_response_summary,
            "错误表现": self.error_pattern,
            ERROR_CAUSE_FIELD: self.error_cause,
            GROUP_COUNT_FIELD: len(self.students),
            "掌握状态": "未开始",
            "系统记录ID": self.system_record_id,
        }
        return values


@dataclass(frozen=True)
class ExistingGroupRecord:
    record_id: str
    system_record_id: str
    students: tuple[str, ...]
    group_count: int
    error_cause: str
    question_record_id: str
    assignment_date: str


@dataclass(frozen=True)
class GroupWriteResult:
    status: str
    student_count: int
    question_error_count: int
    error_rate: float | None
    high_frequency: bool | None


class GroupWriterGateway(Protocol):
    def load(self) -> GroupSchema: ...

    def find_by_system_record_id(
        self, schema: GroupSchema, system_record_id: str
    ) -> tuple[ExistingGroupRecord, ...]: ...

    def create(self, schema: GroupSchema, fields: dict[str, core.JSONValue]) -> None: ...

    def update_group_members(
        self,
        schema: GroupSchema,
        record_id: str,
        students: tuple[str, ...],
        group_count: int,
    ) -> None: ...

    def list_for_question_and_date(
        self, schema: GroupSchema, question_record_id: str, assignment_date: str
    ) -> tuple[ExistingGroupRecord, ...]: ...

    def update_question_projection(
        self,
        schema: GroupSchema,
        question_record_id: str,
        fields: dict[str, core.JSONValue],
    ) -> None: ...

    def read_question_projection(
        self,
        schema: GroupSchema,
        question_record_id: str,
        field_names: tuple[str, ...],
    ) -> dict[str, core.JSONValue]: ...


def write_confirmed_group(
    gateway: GroupWriterGateway, draft: MistakeGroupDraft
) -> GroupWriteResult:
    schema = gateway.load()
    validate_schema(schema)
    existing = gateway.find_by_system_record_id(schema, draft.system_record_id)
    if len(existing) > 1:
        raise core.SkillError(
            "duplicate_system_record_id", "同一系统记录ID对应多条飞书记录，已停止写入。"
        )
    if not existing:
        gateway.create(schema, draft.base_fields())
        status = "created"
        expected = draft.students
    else:
        current = existing[0]
        expected = _merge_students(current.students, draft.students)
        if expected == current.students and current.group_count == len(expected):
            status = "no_change"
        else:
            gateway.update_group_members(schema, current.record_id, expected, len(expected))
            status = "merged"

    readback = gateway.find_by_system_record_id(schema, draft.system_record_id)
    if (
        len(readback) != 1
        or readback[0].students != expected
        or readback[0].group_count != len(expected)
    ):
        raise core.SkillError(
            "lark_readback_mismatch", "错题记录写入后回读不一致，已停止后续操作。"
        )

    groups = gateway.list_for_question_and_date(
        schema, draft.question_record_id, draft.assignment_date
    )
    projection = build_question_projection(
        groups,
        assignment_date=draft.assignment_date,
        sample_size=draft.sample_size,
    )
    gateway.update_question_projection(schema, draft.question_record_id, projection)
    projection_readback = gateway.read_question_projection(
        schema, draft.question_record_id, tuple(projection)
    )
    if any(
        not _projection_cell_matches(projection_readback.get(name), value)
        for name, value in projection.items()
    ):
        raise core.SkillError(
            "lark_readback_mismatch", "题目人数统计写入后回读不一致，已停止后续操作。"
        )
    rate = projection.get("错误率")
    high_frequency = projection.get("是否高频错题")
    return GroupWriteResult(
        status=status,
        student_count=len(expected),
        question_error_count=int(projection["错误人数合计"]),
        error_rate=float(rate) if isinstance(rate, (int, float)) else None,
        high_frequency=high_frequency if isinstance(high_frequency, bool) else None,
    )


def _merge_students(existing: tuple[str, ...], incoming: tuple[str, ...]) -> tuple[str, ...]:
    merged = list(existing)
    seen = set(existing)
    for student in incoming:
        if student not in seen:
            merged.append(student)
            seen.add(student)
    return tuple(merged)


def build_question_projection(
    groups: tuple[ExistingGroupRecord, ...],
    *,
    assignment_date: str,
    sample_size: int | None,
) -> dict[str, core.JSONValue]:
    students: set[str] = set()
    cause_students: dict[str, tuple[str, set[str]]] = {}
    for group in groups:
        if group.assignment_date != assignment_date:
            continue
        students.update(group.students)
        normalized_cause = " ".join(group.error_cause.split())
        if not normalized_cause:
            raise core.SkillError("invalid_payload", "错题记录缺少可统计的错误原因。")
        display, members = cause_students.setdefault(
            normalized_cause, (group.error_cause.strip(), set())
        )
        members.update(group.students)
        cause_students[normalized_cause] = (display, members)

    error_count = len(students)
    if error_count == 0:
        raise core.SkillError("invalid_payload", "错题记录没有可统计的学生。")
    if sample_size is not None and sample_size < error_count:
        raise core.SkillError("invalid_mistake_group", "sampleSize 不能小于该题去重后的错误人数。")
    cause_summary = "；".join(
        f"{display}：{len(members)}人"
        for display, members in sorted(
            cause_students.values(), key=lambda item: (-len(item[1]), item[0])
        )
    )
    projection: dict[str, core.JSONValue] = {
        "统计批次": assignment_date,
        "批改样本人数": None,
        "错误人数合计": error_count,
        "错误率": None,
        ERROR_CAUSE_FIELD: cause_summary,
        "是否高频错题": None,
        "高频判定方式": None,
    }
    if sample_size is not None:
        error_rate = round(error_count / sample_size, 4)
        projection.update(
            {
                "批改样本人数": sample_size,
                "错误率": error_rate,
                "是否高频错题": error_count / sample_size > 0.35,
                "高频判定方式": "批改统计",
            }
        )
    return projection


class LarkGroupSchemaGateway:
    def __init__(
        self,
        runner: core.CommandRunner,
        *,
        base_title: str = core.DEFAULT_BASE_TITLE,
    ) -> None:
        self.runner = runner
        self.base_title = base_title

    def load(self) -> GroupSchema:
        matches: list[tuple[str, dict[str, str]]] = []
        required_tables = {"错题页面", QUESTION_TABLE, GROUP_TABLE}
        for candidate in core.resolve_base_candidates(self.runner, self.base_title):
            table_ids = {
                _required_string(table.get("name")): _required_string(table.get("id"))
                for table in candidate.tables
            }
            if required_tables.issubset(table_ids):
                matches.append((candidate.base_token, table_ids))
        if len(matches) != 1:
            raise core.SkillError("schema_mismatch", "无法唯一定位错题学习 Base。")
        base_token, table_ids = matches[0]
        if STUDENT_TABLE in table_ids:
            raise core.SkillError("unexpected_student_table", "当前最小方案不应存在独立学生表。")
        return GroupSchema(
            table_names=frozenset(table_ids),
            base_token=base_token,
            group_table_id=table_ids[GROUP_TABLE],
            question_table_id=table_ids[QUESTION_TABLE],
            fields=self._fields(base_token, table_ids[GROUP_TABLE]),
            question_fields=self._fields(base_token, table_ids[QUESTION_TABLE]),
        )

    def _fields(self, base_token: str, table_id: str) -> dict[str, FieldState]:
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
        fields: dict[str, FieldState] = {}
        for raw in raw_fields:
            value = _object(raw, "field")
            options_value = value.get("options")
            options = frozenset(
                _required_string(_object(option, "option").get("name"))
                for option in (_list(options_value, "options") if options_value is not None else [])
            )
            name = _required_string(value.get("name"))
            style_value = value.get("style")
            style = style_value if isinstance(style_value, dict) else {}
            precision_value = style.get("precision")
            fields[name] = FieldState(
                field_id=_required_string(value.get("id")),
                name=name,
                field_type=_required_string(value.get("type")),
                multiple=value.get("multiple") if isinstance(value.get("multiple"), bool) else None,
                options=options,
                link_table=value.get("link_table")
                if isinstance(value.get("link_table"), str)
                else None,
                bidirectional=value.get("bidirectional")
                if isinstance(value.get("bidirectional"), bool)
                else None,
                reverse_field_id=value.get("bidirectional_link_field_id")
                if isinstance(value.get("bidirectional_link_field_id"), str)
                else None,
                number_precision=precision_value
                if isinstance(precision_value, int) and not isinstance(precision_value, bool)
                else None,
                number_percentage=style.get("percentage")
                if isinstance(style.get("percentage"), bool)
                else None,
                lookup_from=value.get("from") if isinstance(value.get("from"), str) else None,
                lookup_select_field_id=value.get("select")
                if isinstance(value.get("select"), str)
                else None,
            )
        return fields

    def find_by_system_record_id(
        self, schema: GroupSchema, system_record_id: str
    ) -> tuple[ExistingGroupRecord, ...]:
        filter_json = json.dumps(
            {
                "logic": "and",
                "conditions": [["系统记录ID", "==", system_record_id]],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        envelope = self.runner.run(
            [
                "base",
                "+record-list",
                "--base-token",
                schema.base_token,
                "--table-id",
                schema.group_table_id,
                "--field-id",
                "系统记录ID",
                "--field-id",
                "对应学生",
                "--field-id",
                GROUP_COUNT_FIELD,
                "--field-id",
                ERROR_CAUSE_FIELD,
                "--field-id",
                "对应错题",
                "--field-id",
                "作业日期",
                "--filter-json",
                filter_json,
                "--limit",
                "2",
                "--as",
                "user",
                "--format",
                "json",
            ],
            retry_read=True,
        )
        data = _object(envelope.get("data"), "data")
        if data.get("has_more") is True:
            raise core.SkillError(
                "duplicate_system_record_id",
                "同一系统记录ID对应多条飞书记录，已停止写入。",
            )
        return tuple(
            record
            for record in _group_records_from_columnar(data)
            if record.system_record_id == system_record_id
        )

    def create(self, schema: GroupSchema, fields: dict[str, core.JSONValue]) -> None:
        self._upsert(schema, fields)

    def update_group_members(
        self,
        schema: GroupSchema,
        record_id: str,
        students: tuple[str, ...],
        group_count: int,
    ) -> None:
        self._upsert(
            schema,
            {"对应学生": list(students), GROUP_COUNT_FIELD: group_count},
            record_id=record_id,
        )

    def list_for_question_and_date(
        self, schema: GroupSchema, question_record_id: str, assignment_date: str
    ) -> tuple[ExistingGroupRecord, ...]:
        output: list[ExistingGroupRecord] = []
        offset = 0
        page_size = 200
        field_names = (
            "系统记录ID",
            "对应学生",
            GROUP_COUNT_FIELD,
            ERROR_CAUSE_FIELD,
            "对应错题",
            "作业日期",
        )
        while True:
            arguments = [
                "base",
                "+record-list",
                "--base-token",
                schema.base_token,
                "--table-id",
                schema.group_table_id,
            ]
            for field_name in field_names:
                arguments.extend(("--field-id", field_name))
            arguments.extend(
                (
                    "--offset",
                    str(offset),
                    "--limit",
                    str(page_size),
                    "--as",
                    "user",
                    "--format",
                    "json",
                )
            )
            envelope = self.runner.run(arguments, retry_read=True)
            data = _object(envelope.get("data"), "data")
            records = _group_records_from_columnar(data)
            output.extend(
                record
                for record in records
                if record.question_record_id == question_record_id
                and record.assignment_date == assignment_date
            )
            if data.get("has_more") is not True and len(records) < page_size:
                break
            if not records:
                break
            offset += len(records)
        return tuple(output)

    def update_question_projection(
        self,
        schema: GroupSchema,
        question_record_id: str,
        fields: dict[str, core.JSONValue],
    ) -> None:
        self._upsert_table(
            schema,
            schema.question_table_id,
            fields,
            record_id=question_record_id,
        )

    def read_question_projection(
        self,
        schema: GroupSchema,
        question_record_id: str,
        field_names: tuple[str, ...],
    ) -> dict[str, core.JSONValue]:
        arguments = [
            "base",
            "+record-get",
            "--base-token",
            schema.base_token,
            "--table-id",
            schema.question_table_id,
            "--record-id",
            question_record_id,
        ]
        for field_name in field_names:
            arguments.extend(("--field-id", field_name))
        arguments.extend(("--as", "user", "--format", "json"))
        envelope = self.runner.run(arguments, retry_read=True)
        return _single_record_fields(_object(envelope.get("data"), "data"))

    def _upsert(
        self,
        schema: GroupSchema,
        fields: dict[str, core.JSONValue],
        *,
        record_id: str | None = None,
    ) -> None:
        self._upsert_table(schema, schema.group_table_id, fields, record_id=record_id)

    def _upsert_table(
        self,
        schema: GroupSchema,
        table_id: str,
        fields: dict[str, core.JSONValue],
        *,
        record_id: str | None = None,
    ) -> None:
        arguments = [
            "base",
            "+record-upsert",
            "--base-token",
            schema.base_token,
            "--table-id",
            table_id,
            "--json",
            json.dumps(
                fields,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        ]
        if record_id is not None:
            arguments.extend(("--record-id", record_id))
        arguments.extend(("--as", "user", "--format", "json"))
        self.runner.run(arguments)


def validate_schema(schema: GroupSchema) -> None:
    if STUDENT_TABLE in schema.table_names:
        raise core.SkillError("unexpected_student_table", "当前最小方案不应存在独立学生表。")
    for name, expected_type in EXPECTED_FIELD_TYPES.items():
        field = schema.fields.get(name)
        if field is None or field.field_type != expected_type:
            raise core.SkillError("schema_mismatch", f"错题记录字段无效：{name}。")
    if schema.fields["对应学生"].multiple is not True:
        raise core.SkillError("schema_mismatch", "对应学生必须是多选字段。")
    if schema.fields["错误分类"].multiple is not False:
        raise core.SkillError("schema_mismatch", "错误分类必须是单选字段。")
    if schema.fields["错误分类"].options != ERROR_CATEGORIES:
        raise core.SkillError("schema_mismatch", "错误分类选项与契约不一致。")
    if schema.fields["掌握状态"].options != MASTERY_OPTIONS:
        raise core.SkillError("schema_mismatch", "掌握状态选项与契约不一致。")

    _validate_number_style(
        schema.fields[GROUP_COUNT_FIELD],
        precision=0,
        percentage=False,
        label=GROUP_COUNT_FIELD,
    )

    for name, expected_type in QUESTION_PROJECTION_FIELD_TYPES.items():
        field = schema.question_fields.get(name)
        if field is None or field.field_type != expected_type:
            raise core.SkillError("schema_mismatch", f"错题题目统计字段无效：{name}。")
    high_frequency_method = schema.question_fields["高频判定方式"]
    if (
        high_frequency_method.multiple is not False
        or high_frequency_method.options != HIGH_FREQUENCY_METHODS
    ):
        raise core.SkillError("schema_mismatch", "高频判定方式选项与契约不一致。")

    for count_field in ("批改样本人数", "错误人数合计"):
        _validate_number_style(
            schema.question_fields[count_field],
            precision=0,
            percentage=False,
            label=count_field,
        )
    _validate_number_style(
        schema.question_fields["错误率"],
        precision=1,
        percentage=True,
        label="错误率",
    )

    question_link = schema.fields["对应错题"]
    if (
        question_link.link_table != schema.question_table_id
        or question_link.bidirectional is not True
        or question_link.reverse_field_id is None
    ):
        raise core.SkillError("schema_mismatch", "对应错题必须双向关联错题题目。")
    reverse = schema.question_fields.get("学生错题记录")
    if (
        reverse is None
        or reverse.field_type != "link"
        or reverse.link_table != schema.group_table_id
        or reverse.bidirectional is not True
    ):
        raise core.SkillError("schema_mismatch", "错题题目缺少有效的学生错题记录反向关联。")

    for lookup_name, source_name in QUESTION_GROUP_LOOKUP_FIELDS.items():
        lookup = schema.question_fields.get(lookup_name)
        source = schema.fields[source_name]
        if (
            lookup is None
            or lookup.field_type != "lookup"
            or lookup.lookup_from not in (GROUP_TABLE, schema.group_table_id)
            or lookup.lookup_select_field_id != source.field_id
        ):
            raise core.SkillError(
                "schema_mismatch",
                f"错题题目.{lookup_name} 必须查找引用错题记录.{source_name}。",
            )

    source_image = schema.question_fields.get(QUESTION_IMAGE_LOOKUP_FIELD)
    image_lookup = schema.fields[QUESTION_IMAGE_LOOKUP_FIELD]
    if source_image is None or source_image.field_type != "attachment":
        raise core.SkillError("schema_mismatch", "错题题目缺少题干图片附件字段。")
    if (
        image_lookup.lookup_from not in (QUESTION_TABLE, schema.question_table_id)
        or image_lookup.lookup_select_field_id != source_image.field_id
    ):
        raise core.SkillError("schema_mismatch", "错题记录.题干图片必须引用对应错题的题干图片。")
    source_core = schema.question_fields.get("核心素养")
    core_lookup = schema.fields["核心素养"]
    if source_core is None or source_core.field_type != "select":
        raise core.SkillError("schema_mismatch", "错题题目缺少核心素养多选事实源。")
    if (
        core_lookup.lookup_from not in (QUESTION_TABLE, schema.question_table_id)
        or core_lookup.lookup_select_field_id != source_core.field_id
    ):
        raise core.SkillError("schema_mismatch", "错题记录.核心素养必须引用对应错题。")


def _validate_number_style(
    field: FieldState,
    *,
    precision: int,
    percentage: bool,
    label: str,
) -> None:
    if field.number_precision != precision or field.number_percentage is not percentage:
        expected = "百分比（1 位小数）" if percentage else "整数"
        raise core.SkillError("schema_mismatch", f"{label} 的数字格式必须是{expected}。")


def validate_payload(raw: core.JSONValue) -> MistakeGroupDraft:
    value = core._as_object(raw, "错题分组")
    allowed = {
        "questionRecordId",
        "questionLabel",
        "assignmentDate",
        "errorCategory",
        "students",
        "actualResponseSummary",
        "errorPattern",
        "errorCause",
        "sampleSize",
        # Temporary compatibility for drafts produced before the 2026-07 schema.
        "typicalResponseSummary",
        "teacherDiagnosis",
    }
    if set(value) - allowed:
        raise core.SkillError("invalid_mistake_group", "错题分组包含未支持的字段。")

    question_record_id = core._require_nonempty_text(
        value.get("questionRecordId"), "questionRecordId", maximum=120
    )
    if not question_record_id.startswith("rec"):
        raise core.SkillError("invalid_mistake_group", "questionRecordId 必须是飞书记录 ID。")
    question_label = core._require_nonempty_text(
        value.get("questionLabel"), "questionLabel", maximum=120
    )
    assignment_date = core._require_nonempty_text(
        value.get("assignmentDate"), "assignmentDate", maximum=10
    )
    try:
        date.fromisoformat(assignment_date)
    except ValueError as exc:
        raise core.SkillError(
            "invalid_mistake_group", "assignmentDate 必须是 YYYY-MM-DD。"
        ) from exc

    error_category = core._require_nonempty_text(
        value.get("errorCategory"), "errorCategory", maximum=30
    )
    if error_category not in ERROR_CATEGORIES:
        raise core.SkillError("invalid_mistake_group", "errorCategory 不是约定分类。")

    raw_students = value.get("students")
    if not isinstance(raw_students, list) or not 1 <= len(raw_students) <= 60:
        raise core.SkillError("invalid_mistake_group", "students 必须包含 1～60 个学生姓名或代号。")
    students = tuple(
        core._require_nonempty_text(student, "student", maximum=80).strip()
        for student in raw_students
    )
    if len(set(students)) != len(students):
        raise core.SkillError("invalid_mistake_group", "同一分组中不能重复选择学生。")

    if (
        value.get("actualResponseSummary") is not None
        and value.get("typicalResponseSummary") is not None
    ):
        raise core.SkillError(
            "invalid_mistake_group", "不要同时提供 actualResponseSummary 和旧字段。"
        )
    actual_response_summary = core._require_nonempty_text(
        value.get("actualResponseSummary", value.get("typicalResponseSummary")),
        "actualResponseSummary",
        maximum=10_000,
    )
    error_pattern = core._require_nonempty_text(
        value.get("errorPattern"), "errorPattern", maximum=5_000
    )
    if value.get("errorCause") is not None and value.get("teacherDiagnosis") is not None:
        raise core.SkillError("invalid_mistake_group", "不要同时提供 errorCause 和旧字段。")
    error_cause = core._require_nonempty_text(
        value.get("errorCause", value.get("teacherDiagnosis")),
        "errorCause",
        maximum=5_000,
    )
    raw_sample_size = value.get("sampleSize")
    if raw_sample_size is None:
        sample_size = None
    elif (
        not isinstance(raw_sample_size, int)
        or isinstance(raw_sample_size, bool)
        or not len(students) <= raw_sample_size <= 500
    ):
        raise core.SkillError(
            "invalid_mistake_group",
            "sampleSize 必须是大于等于本组学生数且不超过 500 的整数。",
        )
    else:
        sample_size = raw_sample_size
    return MistakeGroupDraft(
        question_record_id=question_record_id,
        question_label=question_label,
        assignment_date=assignment_date,
        error_category=error_category,
        students=students,
        actual_response_summary=actual_response_summary,
        error_pattern=error_pattern,
        error_cause=error_cause,
        sample_size=sample_size,
    )


def _optional_text(value: core.JSONValue, label: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > maximum:
        raise core.SkillError("invalid_mistake_group", f"{label} 必须是不超过 {maximum} 字的文本。")
    return value.strip()


def _object(value: core.JSONValue, label: str) -> dict[str, core.JSONValue]:
    if not isinstance(value, dict):
        raise core.SkillError("invalid_payload", f"{label} 必须是对象。")
    return value


def _list(value: core.JSONValue, label: str) -> list[core.JSONValue]:
    if not isinstance(value, list):
        raise core.SkillError("invalid_payload", f"{label} 必须是数组。")
    return value


def _required_string(value: core.JSONValue) -> str:
    if not isinstance(value, str) or not value:
        raise core.SkillError("invalid_payload", "飞书返回缺少必要文本字段。")
    return value


def _student_values(value: core.JSONValue) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise core.SkillError("invalid_payload", "对应学生的飞书值不是多选数组。")
    students: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            students.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            students.append(item["text"])
        else:
            raise core.SkillError("invalid_payload", "对应学生包含无法识别的选项。")
    return tuple(students)


def _group_records_from_columnar(
    data: dict[str, core.JSONValue],
) -> tuple[ExistingGroupRecord, ...]:
    output: list[ExistingGroupRecord] = []
    for record in core.parse_columnar_records(data):
        question_ids = _link_ids(record.fields.get("对应错题"))
        if len(question_ids) != 1:
            raise core.SkillError("invalid_payload", "错题记录必须关联且只关联一道题。")
        output.append(
            ExistingGroupRecord(
                record_id=record.record_id,
                system_record_id=_text_cell(record.fields.get("系统记录ID")),
                students=_student_values(record.fields.get("对应学生")),
                group_count=_integer_cell(record.fields.get(GROUP_COUNT_FIELD)),
                error_cause=_text_cell(record.fields.get(ERROR_CAUSE_FIELD)),
                question_record_id=question_ids[0],
                assignment_date=_date_cell(record.fields.get("作业日期")),
            )
        )
    return tuple(output)


def _single_record_fields(
    data: dict[str, core.JSONValue],
) -> dict[str, core.JSONValue]:
    records = core.parse_columnar_records(data)
    if len(records) != 1:
        raise core.SkillError("invalid_payload", "飞书题目回读不是唯一记录。")
    return records[0].fields


def _text_cell(value: core.JSONValue) -> str:
    normalized = _normalized_cell(value)
    if not isinstance(normalized, str) or not normalized.strip():
        raise core.SkillError("invalid_payload", "飞书记录缺少必要文本值。")
    return normalized.strip()


def _integer_cell(value: core.JSONValue) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise core.SkillError("invalid_payload", "飞书记录人数不是数字。")
    integer = int(value)
    if integer != value or integer < 1:
        raise core.SkillError("invalid_payload", "飞书记录人数必须是正整数。")
    return integer


def _link_ids(value: core.JSONValue) -> tuple[str, ...]:
    raw_links = _list(value, "link")
    output: list[str] = []
    for raw in raw_links:
        link = _object(raw, "link")
        output.append(_required_string(link.get("id")))
    return tuple(output)


def _date_cell(value: core.JSONValue) -> str:
    if isinstance(value, str) and len(value) >= 10:
        candidate = value[:10]
        try:
            date.fromisoformat(candidate)
        except ValueError:
            pass
        else:
            return candidate
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        china = timezone(timedelta(hours=8))
        return datetime.fromtimestamp(seconds, tz=UTC).astimezone(china).date().isoformat()
    raise core.SkillError("invalid_payload", "飞书作业日期格式无效。")


def _normalized_cell(value: core.JSONValue) -> core.JSONValue:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and len(value) == 1:
        item = value[0]
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return item["text"].strip()
    return value


def _projection_cell_matches(actual: core.JSONValue, expected: core.JSONValue) -> bool:
    normalized_actual = _normalized_cell(actual)
    normalized_expected = _normalized_cell(expected)
    if normalized_expected is None and core._empty(normalized_actual):
        return True
    return normalized_actual == normalized_expected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-title",
        default=os.environ.get("SHI_HOMEWORK2LARK_BASE_TITLE", core.DEFAULT_BASE_TITLE),
    )
    parser.add_argument(
        "--lark-cli-command", default=os.environ.get("LARK_CLI_COMMAND", "lark-cli")
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema-check")
    for name in ("validate", "preview", "prepare-write", "write"):
        command = commands.add_parser(name)
        command.add_argument("--input", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    core.force_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "schema-check":
            schema = LarkGroupSchemaGateway(
                core.SubprocessRunner(args.lark_cli_command), base_title=args.base_title
            ).load()
            validate_schema(schema)
            result: core.JSONValue = {
                "valid": True,
                "table": GROUP_TABLE,
                "fields": sorted(EXPECTED_FIELD_TYPES),
                "hasStudentTable": False,
            }
        else:
            draft = validate_payload(core.load_json_input(args.input))
            if args.command == "validate":
                result = {
                    "valid": True,
                    "recordName": draft.record_name,
                    "systemRecordId": draft.system_record_id,
                    "studentCount": len(draft.students),
                    "requiresTeacherConfirmation": True,
                }
            elif args.command == "preview":
                result = {
                    "recordName": draft.record_name,
                    "systemRecordId": draft.system_record_id,
                    "studentCount": len(draft.students),
                    "baseFields": draft.base_fields(),
                    "requiresTeacherConfirmation": True,
                }
            elif args.command == "prepare-write":
                result = {
                    "recordName": draft.record_name,
                    "systemRecordId": draft.system_record_id,
                    "studentCount": len(draft.students),
                    "baseFields": draft.base_fields(),
                    "requiresLarkBaseWrite": True,
                }
            elif args.command == "write":
                gateway = LarkGroupSchemaGateway(
                    core.SubprocessRunner(args.lark_cli_command),
                    base_title=args.base_title,
                )
                write_result = write_confirmed_group(gateway, draft)
                result = {
                    "recordName": draft.record_name,
                    "systemRecordId": draft.system_record_id,
                    "studentCount": write_result.student_count,
                    "questionErrorCount": write_result.question_error_count,
                    "errorRate": write_result.error_rate,
                    "highFrequency": write_result.high_frequency,
                    "status": write_result.status,
                    "readbackVerified": True,
                }
            else:
                raise core.SkillError("unsupported_command", "不支持的命令。")
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except core.SkillError as exc:
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
