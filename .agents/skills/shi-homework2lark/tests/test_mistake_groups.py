from __future__ import annotations

import json
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import homework2lark as core  # noqa: E402
import mistake_groups  # noqa: E402


def field(
    name: str,
    field_type: str,
    *,
    multiple: bool | None = None,
    options: frozenset[str] = frozenset(),
    link_table: str | None = None,
    bidirectional: bool | None = None,
    reverse_field_id: str | None = None,
    number_precision: int | None = None,
    number_percentage: bool | None = None,
    lookup_from: str | None = None,
    lookup_select_field_id: str | None = None,
) -> mistake_groups.FieldState:
    return mistake_groups.FieldState(
        field_id=f"field_{name}",
        name=name,
        field_type=field_type,
        multiple=multiple,
        options=options,
        link_table=link_table,
        bidirectional=bidirectional,
        reverse_field_id=reverse_field_id,
        number_precision=number_precision,
        number_percentage=number_percentage,
        lookup_from=lookup_from,
        lookup_select_field_id=lookup_select_field_id,
    )


def valid_schema() -> mistake_groups.GroupSchema:
    fields = {
        name: field(name, field_type)
        for name, field_type in mistake_groups.EXPECTED_FIELD_TYPES.items()
    }
    fields["对应学生"] = field("对应学生", "select", multiple=True)
    fields["对应错题"] = field(
        "对应错题",
        "link",
        link_table="question_table",
        bidirectional=True,
        reverse_field_id="reverse_field",
    )
    fields["错误分类"] = field(
        "错误分类",
        "select",
        multiple=False,
        options=mistake_groups.ERROR_CATEGORIES,
    )
    fields["掌握状态"] = field(
        "掌握状态", "select", multiple=False, options=mistake_groups.MASTERY_OPTIONS
    )
    fields[mistake_groups.GROUP_COUNT_FIELD] = field(
        mistake_groups.GROUP_COUNT_FIELD,
        "number",
        number_precision=0,
        number_percentage=False,
    )
    question_fields = {
        "学生错题记录": field(
            "学生错题记录",
            "link",
            link_table="group_table",
            bidirectional=True,
            reverse_field_id="question_link",
        ),
        **{
            name: field(name, field_type)
            for name, field_type in mistake_groups.QUESTION_PROJECTION_FIELD_TYPES.items()
        },
        mistake_groups.QUESTION_IMAGE_LOOKUP_FIELD: field(
            mistake_groups.QUESTION_IMAGE_LOOKUP_FIELD,
            "attachment",
        ),
        "核心素养": field("核心素养", "select", multiple=True),
    }
    question_fields["高频判定方式"] = field(
        "高频判定方式",
        "select",
        multiple=False,
        options=mistake_groups.HIGH_FREQUENCY_METHODS,
    )
    for count_field in ("批改样本人数", "错误人数合计"):
        question_fields[count_field] = field(
            count_field,
            "number",
            number_precision=0,
            number_percentage=False,
        )
    question_fields["错误率"] = field(
        "错误率",
        "number",
        number_precision=1,
        number_percentage=True,
    )
    for lookup_name, source_name in mistake_groups.QUESTION_GROUP_LOOKUP_FIELDS.items():
        question_fields[lookup_name] = field(
            lookup_name,
            "lookup",
            lookup_from="错题记录",
            lookup_select_field_id=fields[source_name].field_id,
        )
    fields[mistake_groups.QUESTION_IMAGE_LOOKUP_FIELD] = field(
        mistake_groups.QUESTION_IMAGE_LOOKUP_FIELD,
        "lookup",
        lookup_from="错题题目",
        lookup_select_field_id=question_fields[mistake_groups.QUESTION_IMAGE_LOOKUP_FIELD].field_id,
    )
    fields["核心素养"] = field(
        "核心素养",
        "lookup",
        lookup_from="错题题目",
        lookup_select_field_id=question_fields["核心素养"].field_id,
    )
    return mistake_groups.GroupSchema(
        table_names=frozenset(("错题页面", "错题题目", "错题记录")),
        base_token="base_token",
        group_table_id="group_table",
        question_table_id="question_table",
        fields=fields,
        question_fields=question_fields,
    )


def payload() -> dict[str, core.JSONValue]:
    return {
        "questionRecordId": "rec_question_alpha",
        "questionLabel": "商的位数与连续减法问题",
        "assignmentDate": "2026-07-14",
        "errorCategory": "运算与计算",
        "students": ["学生代号A", "学生代号B"],
        "actualResponseSummary": "两人都把最后一个空填写为11。",
        "errorPattern": "把相邻整十数判断成70，没有进到下一个整十数。",
        "errorCause": "没有把连续减8理解为96里面包含几个8。",
        "sampleSize": 37,
    }


class MistakeGroupContractTest(unittest.TestCase):
    def test_valid_schema_allows_grouped_students_without_student_table(self) -> None:
        mistake_groups.validate_schema(valid_schema())

    def test_schema_rejects_whole_number_error_rate_display(self) -> None:
        schema = valid_schema()
        question_fields = dict(schema.question_fields)
        question_fields["错误率"] = field(
            "错误率",
            "number",
            number_precision=2,
            number_percentage=False,
        )
        invalid = mistake_groups.GroupSchema(
            table_names=schema.table_names,
            base_token=schema.base_token,
            group_table_id=schema.group_table_id,
            question_table_id=schema.question_table_id,
            fields=schema.fields,
            question_fields=question_fields,
        )

        with self.assertRaises(core.SkillError) as captured:
            mistake_groups.validate_schema(invalid)

        self.assertEqual(captured.exception.code, "schema_mismatch")

    def test_schema_rejects_question_image_lookup_from_wrong_table(self) -> None:
        schema = valid_schema()
        fields = dict(schema.fields)
        fields[mistake_groups.QUESTION_IMAGE_LOOKUP_FIELD] = field(
            mistake_groups.QUESTION_IMAGE_LOOKUP_FIELD,
            "lookup",
            lookup_from="错题页面",
            lookup_select_field_id=schema.question_fields[
                mistake_groups.QUESTION_IMAGE_LOOKUP_FIELD
            ].field_id,
        )
        invalid = mistake_groups.GroupSchema(
            table_names=schema.table_names,
            base_token=schema.base_token,
            group_table_id=schema.group_table_id,
            question_table_id=schema.question_table_id,
            fields=fields,
            question_fields=schema.question_fields,
        )

        with self.assertRaises(core.SkillError) as captured:
            mistake_groups.validate_schema(invalid)

        self.assertEqual(captured.exception.code, "schema_mismatch")

    def test_schema_rejects_question_error_pattern_lookup_from_wrong_table(self) -> None:
        schema = valid_schema()
        question_fields = dict(schema.question_fields)
        question_fields[mistake_groups.ERROR_PATTERN_FIELD] = field(
            mistake_groups.ERROR_PATTERN_FIELD,
            "lookup",
            lookup_from="错题页面",
            lookup_select_field_id=schema.fields[mistake_groups.ERROR_PATTERN_FIELD].field_id,
        )
        invalid = mistake_groups.GroupSchema(
            table_names=schema.table_names,
            base_token=schema.base_token,
            group_table_id=schema.group_table_id,
            question_table_id=schema.question_table_id,
            fields=schema.fields,
            question_fields=question_fields,
        )

        with self.assertRaises(core.SkillError) as captured:
            mistake_groups.validate_schema(invalid)

        self.assertEqual(captured.exception.code, "schema_mismatch")

    def test_schema_rejects_independent_student_table(self) -> None:
        schema = valid_schema()
        invalid = mistake_groups.GroupSchema(
            table_names=schema.table_names | {"学生"},
            base_token=schema.base_token,
            group_table_id=schema.group_table_id,
            question_table_id=schema.question_table_id,
            fields=schema.fields,
            question_fields=schema.question_fields,
        )

        with self.assertRaises(core.SkillError) as captured:
            mistake_groups.validate_schema(invalid)

        self.assertEqual(captured.exception.code, "unexpected_student_table")

    def test_group_payload_keeps_same_error_students_in_one_row(self) -> None:
        draft = mistake_groups.validate_payload(payload())
        base_fields = draft.base_fields()

        self.assertEqual(base_fields["对应学生"], ["学生代号A", "学生代号B"])
        self.assertEqual(base_fields["对应错题"], [{"id": "rec_question_alpha"}])
        self.assertEqual(base_fields[mistake_groups.GROUP_COUNT_FIELD], 2)
        self.assertEqual(
            base_fields[mistake_groups.ACTUAL_RESPONSE_FIELD],
            "两人都把最后一个空填写为11。",
        )
        self.assertNotIn("学生代号A", draft.record_name)
        self.assertNotIn("学生代号A", draft.system_record_id)

    def test_preview_and_write_share_the_same_durable_fields(self) -> None:
        draft = mistake_groups.validate_payload(payload())
        preview = draft.base_fields()
        confirmed = draft.base_fields()

        self.assertEqual(preview, confirmed)

    def test_stable_key_does_not_change_when_same_group_adds_a_student(self) -> None:
        first = mistake_groups.validate_payload(payload())
        expanded_payload = payload()
        expanded_payload["students"] = ["学生代号A", "学生代号B", "学生代号C"]
        expanded = mistake_groups.validate_payload(expanded_payload)

        self.assertEqual(first.system_record_id, expanded.system_record_id)
        self.assertNotIn("学生代号C", expanded.system_record_id)

    def test_stable_key_groups_by_cause_not_response_wording(self) -> None:
        first = mistake_groups.validate_payload(payload())
        changed_response = payload()
        changed_response["actualResponseSummary"] = "可见有人写11，也有人把空留白。"
        changed_response["errorPattern"] = "最后一空出现11或未作答。"
        second = mistake_groups.validate_payload(changed_response)

        self.assertEqual(first.system_record_id, second.system_record_id)

        changed_cause = payload()
        changed_cause["errorCause"] = "把96÷8误算为11。"
        third = mistake_groups.validate_payload(changed_cause)
        self.assertNotEqual(first.system_record_id, third.system_record_id)

    def test_duplicate_student_in_one_group_is_rejected(self) -> None:
        invalid = payload()
        invalid["students"] = ["学生代号A", "学生代号A"]

        with self.assertRaises(core.SkillError) as captured:
            mistake_groups.validate_payload(invalid)

        self.assertEqual(captured.exception.code, "invalid_mistake_group")

    def test_unknown_error_category_is_rejected(self) -> None:
        invalid = payload()
        invalid["errorCategory"] = "粗心"

        with self.assertRaises(core.SkillError) as captured:
            mistake_groups.validate_payload(invalid)

        self.assertEqual(captured.exception.code, "invalid_mistake_group")

    def test_question_projection_deduplicates_students_and_uses_strict_35_percent(
        self,
    ) -> None:
        def group(
            record_id: str, cause: str, students: tuple[str, ...]
        ) -> mistake_groups.ExistingGroupRecord:
            return mistake_groups.ExistingGroupRecord(
                record_id=record_id,
                system_record_id=f"group_{record_id}",
                students=students,
                group_count=len(students),
                error_cause=cause,
                question_record_id="rec_question_alpha",
                assignment_date="2026-07-14",
            )

        twelve = tuple(f"学生{index}" for index in range(1, 13))
        not_high = mistake_groups.build_question_projection(
            (group("one", "共同错因", twelve),),
            assignment_date="2026-07-14",
            sample_size=37,
        )
        self.assertEqual(not_high["错误人数合计"], 12)
        self.assertFalse(not_high["是否高频错题"])

        overlapping = tuple(f"学生{index}" for index in range(8, 14))
        high = mistake_groups.build_question_projection(
            (
                group("one", "错因甲", tuple(f"学生{index}" for index in range(1, 11))),
                group("two", "错因乙", overlapping),
            ),
            assignment_date="2026-07-14",
            sample_size=37,
        )
        self.assertEqual(high["错误人数合计"], 13)
        self.assertEqual(high["错误率"], 0.3514)
        self.assertTrue(high["是否高频错题"])
        self.assertIn("错因甲：10人", str(high[mistake_groups.ERROR_CAUSE_FIELD]))
        self.assertIn("错因乙：6人", str(high[mistake_groups.ERROR_CAUSE_FIELD]))

        without_sample = mistake_groups.build_question_projection(
            (group("one", "共同错因", twelve),),
            assignment_date="2026-07-14",
            sample_size=None,
        )
        for field_name in (
            "批改样本人数",
            "错误率",
            "是否高频错题",
            "高频判定方式",
        ):
            self.assertIn(field_name, without_sample)
            self.assertIsNone(without_sample[field_name])

    def test_confirmed_write_creates_then_merges_students_idempotently(self) -> None:
        class FakeGateway:
            def __init__(self) -> None:
                self.schema = valid_schema()
                self.records: list[mistake_groups.ExistingGroupRecord] = []
                self.question_projection: dict[str, core.JSONValue] = {}

            def load(self) -> mistake_groups.GroupSchema:
                return self.schema

            def find_by_system_record_id(
                self, schema: mistake_groups.GroupSchema, system_record_id: str
            ) -> tuple[mistake_groups.ExistingGroupRecord, ...]:
                return tuple(
                    record for record in self.records if record.system_record_id == system_record_id
                )

            def create(
                self,
                schema: mistake_groups.GroupSchema,
                fields: dict[str, core.JSONValue],
            ) -> None:
                raw_students = fields["对应学生"]
                assert isinstance(raw_students, list)
                self.records.append(
                    mistake_groups.ExistingGroupRecord(
                        record_id="rec_group",
                        system_record_id=str(fields["系统记录ID"]),
                        students=tuple(str(value) for value in raw_students),
                        group_count=int(fields[mistake_groups.GROUP_COUNT_FIELD]),
                        error_cause=str(fields[mistake_groups.ERROR_CAUSE_FIELD]),
                        question_record_id="rec_question_alpha",
                        assignment_date="2026-07-14",
                    )
                )

            def update_group_members(
                self,
                schema: mistake_groups.GroupSchema,
                record_id: str,
                students: tuple[str, ...],
                group_count: int,
            ) -> None:
                current = self.records[0]
                self.records[0] = mistake_groups.ExistingGroupRecord(
                    record_id=current.record_id,
                    system_record_id=current.system_record_id,
                    students=students,
                    group_count=group_count,
                    error_cause=current.error_cause,
                    question_record_id=current.question_record_id,
                    assignment_date=current.assignment_date,
                )

            def list_for_question_and_date(
                self,
                schema: mistake_groups.GroupSchema,
                question_record_id: str,
                assignment_date: str,
            ) -> tuple[mistake_groups.ExistingGroupRecord, ...]:
                return tuple(
                    record
                    for record in self.records
                    if record.question_record_id == question_record_id
                    and record.assignment_date == assignment_date
                )

            def update_question_projection(
                self,
                schema: mistake_groups.GroupSchema,
                question_record_id: str,
                fields: dict[str, core.JSONValue],
            ) -> None:
                self.question_projection = dict(fields)

            def read_question_projection(
                self,
                schema: mistake_groups.GroupSchema,
                question_record_id: str,
                field_names: tuple[str, ...],
            ) -> dict[str, core.JSONValue]:
                return {name: self.question_projection.get(name) for name in field_names}

        gateway = FakeGateway()
        first = mistake_groups.validate_payload(payload())
        created = mistake_groups.write_confirmed_group(gateway, first)
        self.assertEqual((created.status, created.student_count), ("created", 2))
        self.assertEqual(created.question_error_count, 2)
        self.assertEqual(created.error_rate, 0.0541)
        self.assertFalse(created.high_frequency)

        expanded_payload = payload()
        expanded_payload["students"] = ["学生代号A", "学生代号B", "学生代号C"]
        expanded = mistake_groups.validate_payload(expanded_payload)
        merged = mistake_groups.write_confirmed_group(gateway, expanded)
        self.assertEqual((merged.status, merged.student_count), ("merged", 3))

        unchanged = mistake_groups.write_confirmed_group(gateway, expanded)
        self.assertEqual((unchanged.status, unchanged.student_count), ("no_change", 3))

    def test_live_gateway_filters_by_stable_key_instead_of_scanning_table(self) -> None:
        class FakeRunner:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def run(
                self, args: Sequence[str], *, retry_read: bool = False
            ) -> dict[str, core.JSONValue]:
                self.calls.append(list(args))
                return {
                    "ok": True,
                    "data": {
                        "fields": [
                            "系统记录ID",
                            "对应学生",
                            mistake_groups.GROUP_COUNT_FIELD,
                            mistake_groups.ERROR_CAUSE_FIELD,
                            "对应错题",
                            "作业日期",
                        ],
                        "data": [
                            [
                                "mistake_group_alpha",
                                ["学生代号A"],
                                1,
                                "共同错因",
                                [{"id": "rec_question_alpha"}],
                                "2026-07-14 00:00:00",
                            ]
                        ],
                        "record_id_list": ["rec_group"],
                        "has_more": False,
                    },
                }

        runner = FakeRunner()
        gateway = mistake_groups.LarkGroupSchemaGateway(runner)
        records = gateway.find_by_system_record_id(valid_schema(), "mistake_group_alpha")

        self.assertEqual(records[0].students, ("学生代号A",))
        call = runner.calls[0]
        self.assertEqual(call[call.index("--limit") + 1], "2")
        filter_json = json.loads(call[call.index("--filter-json") + 1])
        self.assertEqual(
            filter_json,
            {
                "logic": "and",
                "conditions": [["系统记录ID", "==", "mistake_group_alpha"]],
            },
        )

    def test_confirmed_write_rejects_duplicate_stable_keys(self) -> None:
        class DuplicateGateway:
            def load(self) -> mistake_groups.GroupSchema:
                return valid_schema()

            def find_by_system_record_id(
                self, schema: mistake_groups.GroupSchema, system_record_id: str
            ) -> tuple[mistake_groups.ExistingGroupRecord, ...]:
                return (
                    mistake_groups.ExistingGroupRecord(
                        "rec_one",
                        system_record_id,
                        ("学生代号A",),
                        1,
                        "共同错因",
                        "rec_question_alpha",
                        "2026-07-14",
                    ),
                    mistake_groups.ExistingGroupRecord(
                        "rec_two",
                        system_record_id,
                        ("学生代号B",),
                        1,
                        "共同错因",
                        "rec_question_alpha",
                        "2026-07-14",
                    ),
                )

            def create(
                self,
                schema: mistake_groups.GroupSchema,
                fields: dict[str, core.JSONValue],
            ) -> None:
                raise AssertionError("duplicate keys must stop before create")

            def update_group_members(
                self,
                schema: mistake_groups.GroupSchema,
                record_id: str,
                students: tuple[str, ...],
                group_count: int,
            ) -> None:
                raise AssertionError("duplicate keys must stop before update")

        with self.assertRaises(core.SkillError) as captured:
            mistake_groups.write_confirmed_group(
                DuplicateGateway(), mistake_groups.validate_payload(payload())
            )

        self.assertEqual(captured.exception.code, "duplicate_system_record_id")

    def test_confirmed_write_requires_matching_readback(self) -> None:
        class MissingReadbackGateway:
            def load(self) -> mistake_groups.GroupSchema:
                return valid_schema()

            def find_by_system_record_id(
                self, schema: mistake_groups.GroupSchema, system_record_id: str
            ) -> tuple[mistake_groups.ExistingGroupRecord, ...]:
                return ()

            def create(
                self,
                schema: mistake_groups.GroupSchema,
                fields: dict[str, core.JSONValue],
            ) -> None:
                return None

            def update_group_members(
                self,
                schema: mistake_groups.GroupSchema,
                record_id: str,
                students: tuple[str, ...],
                group_count: int,
            ) -> None:
                raise AssertionError("new records do not update")

        with self.assertRaises(core.SkillError) as captured:
            mistake_groups.write_confirmed_group(
                MissingReadbackGateway(), mistake_groups.validate_payload(payload())
            )

        self.assertEqual(captured.exception.code, "lark_readback_mismatch")


if __name__ == "__main__":
    unittest.main()
