from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import homework2lark as core  # noqa: E402
import mistake_groups as group_contract  # noqa: E402
import practice_sheet  # noqa: E402
import variant_catalog  # noqa: E402

QUESTION_TABLE = "错题题目"
GROUP_TABLE = "错题记录"
VARIANT_TABLE = "变式题"

DEFAULT_QUESTION_COUNT = 6
MIN_QUESTION_COUNT = 1
MAX_QUESTION_COUNT = 12
SUPPORTED_IMAGE_SUFFIXES = frozenset((".jpg", ".jpeg", ".png"))

MASTERY_PRIORITY = {
    "需再练": 3,
    "练习中": 2,
    "未开始": 1,
    "已掌握": 0,
}

ANSWER_LINES_BY_TYPE = {
    "选择题": 0,
    "填空题": 0,
    "判断题": 0,
    "计算题": 3,
    "解答题": 4,
    "应用题": 4,
    "操作题": 3,
    "开放题": 5,
    "其他": 2,
}


@dataclass(frozen=True)
class RosterStudent:
    name: str
    student_number: str
    instance_code: str


@dataclass(frozen=True)
class AttachmentRef:
    table_name: str
    record_id: str
    file_token: str
    suffix: str
    description: str


@dataclass(frozen=True)
class PracticeAsset:
    source_type: str
    question_id: str
    variant_id: str | None
    variant_number: int | None
    question: str
    answer_lines: int
    attachment: AttachmentRef | None = None


@dataclass(frozen=True)
class MistakeEvidence:
    mastery: str
    error_category: str
    assignment_date: date
    latest_retry_date: date | None = None


@dataclass(frozen=True)
class QuestionBundle:
    original: PracticeAsset
    variants: tuple[PracticeAsset, ...]
    evidence: tuple[MistakeEvidence, ...]


@dataclass(frozen=True)
class PersonalPracticeData:
    bundles: tuple[QuestionBundle, ...]
    skipped_invalid_records: int = 0


@dataclass(frozen=True)
class BundleProfile:
    bundle: QuestionBundle
    mastery: str
    priority: int
    error_category: str
    evidence_date: date
    latest_retry_date: date | None


@dataclass(frozen=True)
class SelectedAsset:
    asset: PracticeAsset
    profile: BundleProfile
    selection_kind: str


class PersonalPracticeGateway(Protocol):
    def validate_schema(self) -> dict[str, core.JSONValue]: ...

    def load_for_student(self, student_name: str) -> PersonalPracticeData: ...

    def materialize_attachment(
        self,
        attachment: AttachmentRef,
        destination: Path,
    ) -> None: ...


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _private_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise core.SkillError("invalid_roster", f"{label} 必须是非空文本。")
    text = value.strip()
    if len(text) > maximum or any(ord(character) < 32 for character in text):
        raise core.SkillError("invalid_roster", f"{label} 格式无效。")
    return text


def load_roster(path: Path) -> tuple[RosterStudent, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise core.SkillError("input_unreadable", "班级名单文件不可读取。") from exc
    except json.JSONDecodeError as exc:
        raise core.SkillError("invalid_roster", "班级名单不是有效 JSON。") from exc
    if not isinstance(raw, dict) or set(raw) != {"students"}:
        raise core.SkillError("invalid_roster", "班级名单顶层只能包含 students。")
    students_raw = raw["students"]
    if not isinstance(students_raw, list) or not 1 <= len(students_raw) <= 500:
        raise core.SkillError("invalid_roster", "students 必须包含 1～500 名学生。")

    students: list[RosterStudent] = []
    numbers: set[str] = set()
    names: set[str] = set()
    for index, value in enumerate(students_raw, start=1):
        if not isinstance(value, Mapping) or set(value) != {"studentNumber", "name"}:
            raise core.SkillError(
                "invalid_roster",
                "每名学生必须且只能包含 studentNumber 和 name。",
            )
        number = _private_text(value["studentNumber"], "学号", 20)
        name = _private_text(value["name"], "姓名", 40)
        if number in numbers:
            raise core.SkillError("duplicate_student_number", "班级名单存在重复学号。")
        if name in names:
            raise core.SkillError(
                "ambiguous_student_name",
                "班级名单存在同名学生；当前 Base 只有姓名，不能可靠区分。",
            )
        numbers.add(number)
        names.add(name)
        students.append(RosterStudent(name, number, f"S{index:03d}"))
    return tuple(students)


def resolve_student(roster: Sequence[RosterStudent], student_number: str) -> RosterStudent:
    target = student_number.strip()
    matches = [student for student in roster if student.student_number == target]
    if len(matches) != 1:
        raise core.SkillError("student_not_found", "班级名单中没有唯一匹配的学号。")
    return matches[0]


def _profile_bundle(
    bundle: QuestionBundle,
    *,
    include_mastered: bool,
) -> BundleProfile | None:
    eligible = [
        evidence for evidence in bundle.evidence if include_mastered or evidence.mastery != "已掌握"
    ]
    if not eligible:
        return None
    priority = max(MASTERY_PRIORITY[evidence.mastery] for evidence in eligible)
    same_priority = [
        evidence for evidence in eligible if MASTERY_PRIORITY[evidence.mastery] == priority
    ]
    current = max(
        same_priority,
        key=lambda evidence: (
            max(
                evidence.assignment_date,
                evidence.latest_retry_date or evidence.assignment_date,
            ),
            evidence.assignment_date,
            evidence.error_category,
        ),
    )
    effective_date = max(
        current.assignment_date,
        current.latest_retry_date or current.assignment_date,
    )
    return BundleProfile(
        bundle=bundle,
        mastery=current.mastery,
        priority=priority,
        error_category=current.error_category,
        evidence_date=effective_date,
        latest_retry_date=current.latest_retry_date,
    )


def order_bundles(
    bundles: Sequence[QuestionBundle],
    *,
    include_mastered: bool = False,
) -> tuple[BundleProfile, ...]:
    profiles = [
        profile
        for bundle in bundles
        if (profile := _profile_bundle(bundle, include_mastered=include_mastered)) is not None
    ]
    ordered: list[BundleProfile] = []
    for priority in sorted(MASTERY_PRIORITY.values(), reverse=True):
        tier = [profile for profile in profiles if profile.priority == priority]
        tier.sort(
            key=lambda profile: (
                -profile.evidence_date.toordinal(),
                -(profile.latest_retry_date or date.min).toordinal(),
                profile.bundle.original.question_id,
            )
        )
        category_buckets: dict[str, list[BundleProfile]] = {}
        for profile in tier:
            category_buckets.setdefault(profile.error_category, []).append(profile)
        while any(category_buckets.values()):
            for bucket in category_buckets.values():
                if bucket:
                    ordered.append(bucket.pop(0))
    return tuple(ordered)


def select_assets(
    bundles: Sequence[QuestionBundle],
    question_count: int,
    *,
    include_mastered: bool = False,
) -> tuple[SelectedAsset, ...]:
    if isinstance(question_count, bool) or not (
        MIN_QUESTION_COUNT <= question_count <= MAX_QUESTION_COUNT
    ):
        raise core.SkillError(
            "invalid_question_count",
            f"题量必须是 {MIN_QUESTION_COUNT}～{MAX_QUESTION_COUNT} 的整数。",
        )
    profiles = order_bundles(bundles, include_mastered=include_mastered)
    if not profiles:
        raise core.SkillError(
            "no_eligible_questions",
            "该学生没有可用于个人练习的错题。",
        )

    primary_profiles = profiles[:question_count]
    selected = [
        SelectedAsset(profile.bundle.original, profile, "原题确认") for profile in primary_profiles
    ]
    if len(selected) >= question_count:
        return tuple(selected)

    variant_offsets = {profile.bundle.original.question_id: 0 for profile in profiles}
    while len(selected) < question_count:
        added = False
        for profile in profiles:
            question_id = profile.bundle.original.question_id
            offset = variant_offsets[question_id]
            if offset >= len(profile.bundle.variants):
                continue
            selected.append(
                SelectedAsset(
                    profile.bundle.variants[offset],
                    profile,
                    "变式迁移",
                )
            )
            variant_offsets[question_id] = offset + 1
            added = True
            if len(selected) >= question_count:
                break
        if not added:
            break
    return tuple(selected)


def _source_payload(asset: PracticeAsset) -> dict[str, str]:
    payload = {"type": asset.source_type, "questionId": asset.question_id}
    if asset.source_type == "variant":
        if asset.variant_id is None:
            raise core.SkillError("asset_incomplete", "变式题缺少稳定来源 ID。")
        payload["variantId"] = asset.variant_id
    return payload


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class PersonalPracticeService:
    def __init__(self, gateway: PersonalPracticeGateway) -> None:
        self.gateway = gateway

    def schema_check(self) -> dict[str, core.JSONValue]:
        return self.gateway.validate_schema()

    def plan(
        self,
        *,
        roster_path: Path,
        student_number: str,
        batch_code: str,
        question_count: int,
        output_dir: Path,
        include_mastered: bool = False,
    ) -> dict[str, core.JSONValue]:
        practice_sheet._validate_batch_code(batch_code)
        roster = load_roster(roster_path)
        student = resolve_student(roster, student_number)
        data = self.gateway.load_for_student(student.name)
        selected = select_assets(
            data.bundles,
            question_count,
            include_mastered=include_mastered,
        )

        destination = output_dir.expanduser().resolve()
        if destination.exists():
            raise core.SkillError(
                "output_exists",
                "输出目录已存在；请为本次个人练习使用新的目录。",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        working = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex[:8]}"
        working.mkdir()

        try:
            manifest_items: list[dict[str, object]] = []
            report_items: list[dict[str, object]] = []
            for item_number, selection in enumerate(selected, start=1):
                item_code = f"R{item_number:02d}"
                asset = selection.asset
                manifest_item: dict[str, object] = {
                    "itemCode": item_code,
                    "question": asset.question,
                    "answerLines": asset.answer_lines,
                    "source": _source_payload(asset),
                }
                if asset.attachment is not None:
                    relative_image = Path("images") / f"{item_code}{asset.attachment.suffix}"
                    local_image = working / relative_image
                    local_image.parent.mkdir(parents=True, exist_ok=True)
                    self.gateway.materialize_attachment(asset.attachment, local_image)
                    manifest_item["stemImage"] = {
                        "path": relative_image.as_posix(),
                        "description": asset.attachment.description,
                    }
                manifest_items.append(manifest_item)
                report_items.append(
                    {
                        "itemCode": item_code,
                        "sourceQuestionId": asset.question_id,
                        "variantId": asset.variant_id,
                        "mastery": selection.profile.mastery,
                        "evidenceDate": selection.profile.evidence_date.isoformat(),
                        "errorCategory": selection.profile.error_category,
                        "selection": selection.selection_kind,
                    }
                )

            manifest = {
                "batchCode": batch_code,
                "manifestVersion": practice_sheet.PERSONAL_MANIFEST_VERSION,
                "student": {
                    "name": student.name,
                    "studentNumber": student.student_number,
                    "instanceCode": student.instance_code,
                },
                "items": manifest_items,
            }
            report = {
                "batchCode": batch_code,
                "student": {
                    "name": student.name,
                    "studentNumber": student.student_number,
                    "instanceCode": student.instance_code,
                },
                "requestedQuestionCount": question_count,
                "selectedQuestionCount": len(selected),
                "includeMastered": include_mastered,
                "skippedInvalidRecords": data.skipped_invalid_records,
                "items": report_items,
            }
            _write_json(working / "manifest.json", manifest)
            _write_json(working / "selection.json", report)
            practice_sheet._load_manifest(working / "manifest.json")
            working.replace(destination)
        except Exception:
            shutil.rmtree(working, ignore_errors=True)
            raise

        return {
            "requested": question_count,
            "selected": len(selected),
            "layout": "word_auto_flow",
            "manifest": "manifest.json",
            "selection": "selection.json",
        }


def student_filter(student_name: str) -> dict[str, core.JSONValue]:
    return {
        "logic": "and",
        "conditions": [["对应学生", "intersects", [student_name]]],
    }


def _attachment_ref(
    value: core.JSONValue,
    *,
    table_name: str,
    record_id: str,
    description: str,
) -> AttachmentRef | None:
    if value in (None, [], ""):
        return None
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise core.SkillError("asset_incomplete", "题干图片必须且只能包含一个附件。")
    raw = value[0]
    token = raw.get("file_token") or raw.get("token") or raw.get("fileToken")
    if not isinstance(token, str) or not token:
        raise core.SkillError("asset_incomplete", "题干图片缺少可下载文件标识。")
    name = raw.get("name") or raw.get("file_name") or raw.get("fileName") or ""
    suffix = Path(name).suffix.lower() if isinstance(name, str) else ""
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        mime = raw.get("type") or raw.get("mime_type") or raw.get("mimeType")
        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
        }.get(mime, "")
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise core.SkillError("asset_incomplete", "题干图片不是支持的 JPG 或 PNG。")
    return AttachmentRef(table_name, record_id, token, suffix, description)


def _answer_lines(question_type: str) -> int:
    return ANSWER_LINES_BY_TYPE.get(question_type, 2)


def _optional_date(value: core.JSONValue) -> date | None:
    if value in (None, "", []):
        return None
    return date.fromisoformat(group_contract._date_cell(value))


class LarkPersonalPracticeGateway:
    def __init__(
        self,
        runner: core.CommandRunner,
        *,
        base_title: str = core.DEFAULT_BASE_TITLE,
    ) -> None:
        self.runner = runner
        self.base_title = base_title
        self.questions = core.LarkCliGateway(
            runner,
            base_title=base_title,
            table_name=QUESTION_TABLE,
        )
        self.groups = core.LarkCliGateway(
            runner,
            base_title=base_title,
            table_name=GROUP_TABLE,
        )
        self.group_contract = group_contract.LarkGroupSchemaGateway(
            runner,
            base_title=base_title,
        )
        self.catalog = variant_catalog.VariantCatalogGateway(
            runner,
            base_title=base_title,
        )
        self._schema_result: dict[str, core.JSONValue] | None = None
        self._group_student_options: frozenset[str] = frozenset()
        self._question_schema_cache: core.BaseSchema | None = None
        self._entries_by_question_cache: (
            dict[str, tuple[variant_catalog.CatalogEntry, ...]] | None
        ) = None
        self._asset_cache: dict[
            str,
            tuple[PracticeAsset, tuple[PracticeAsset, ...]],
        ] = {}
        self._attachment_bytes: dict[tuple[str, str, str], bytes] = {}

    def validate_schema(self) -> dict[str, core.JSONValue]:
        if self._schema_result is not None:
            return dict(self._schema_result)
        group_schema = self.group_contract.load()
        group_contract.validate_schema(group_schema)
        self._group_student_options = group_schema.fields["对应学生"].options
        self.catalog.validate_schema()
        question_schema = self.questions.schema()
        required_question_fields = {
            core.question_id_field(question_schema): "text",
            "题目名称": "text",
            "题干文本": "text",
            "图片题目": "attachment",
            "题干图片": "attachment",
            "题型": "select",
            "本地修订版本": "number",
            core.MANUAL_ATTENTION_FIELD: "checkbox",
        }
        errors = [
            name
            for name, expected in required_question_fields.items()
            if question_schema.fields.get(name) is None
            or question_schema.fields[name].field_type != expected
        ]
        if errors:
            raise core.SkillError(
                "schema_mismatch",
                "个人练习所需题目字段缺失或类型不匹配。",
            )
        self._question_schema_cache = question_schema
        self._schema_result = {
            "tables": [QUESTION_TABLE, GROUP_TABLE, VARIANT_TABLE],
            "personalPractice": "ready",
        }
        return dict(self._schema_result)

    def _question_schema(self) -> core.BaseSchema:
        self.validate_schema()
        if self._question_schema_cache is None:
            raise core.SkillError("schema_mismatch", "题目表结构缓存不可用。")
        return self._question_schema_cache

    def _entries_by_question(
        self,
    ) -> dict[str, tuple[variant_catalog.CatalogEntry, ...]]:
        if self._entries_by_question_cache is None:
            grouped: dict[str, list[variant_catalog.CatalogEntry]] = {}
            for entry in self.catalog.list_entries():
                grouped.setdefault(entry.source_record_id, []).append(entry)
            self._entries_by_question_cache = {
                record_id: tuple(sorted(entries, key=lambda item: item.number))
                for record_id, entries in grouped.items()
            }
        return self._entries_by_question_cache

    def _assets_for_question(
        self,
        question_record_id: str,
    ) -> tuple[PracticeAsset, tuple[PracticeAsset, ...]]:
        cached = self._asset_cache.get(question_record_id)
        if cached is not None:
            return cached

        question_schema = self._question_schema()
        question_fields = tuple(
            field
            for field in (
                core.question_id_field(question_schema),
                "题目名称",
                "题干文本",
                "图片题目",
                "题干图片",
                "题型",
                "图表说明",
                "本地修订版本",
                core.MANUAL_ATTENTION_FIELD,
            )
            if field in question_schema.fields
        )
        record = self.questions.get_record(question_record_id, question_fields)
        core.ensure_source_eligible(record)
        question_id = core.question_id(record)
        label = core._text(record.fields.get("题目名称")) or "题目"
        question_text = core._text(record.fields.get("题干文本"))
        stem_description = core._text(record.fields.get("图表说明")) or f"{label}的题干图片"
        stem = _attachment_ref(
            record.fields.get("题干图片"),
            table_name=QUESTION_TABLE,
            record_id=record.record_id,
            description=stem_description,
        )
        if not question_text:
            stem = _attachment_ref(
                record.fields.get("图片题目"),
                table_name=QUESTION_TABLE,
                record_id=record.record_id,
                description=f"{label}的完整题目图片",
            )
            if stem is None:
                raise core.SkillError("asset_incomplete", "原题内容不完整。")
            question_text = "请完成下面这道题。"
        answer_lines = _answer_lines(core._select(record.fields.get("题型")) or "其他")
        original = PracticeAsset(
            source_type="original",
            question_id=question_id,
            variant_id=None,
            variant_number=None,
            question=question_text,
            answer_lines=answer_lines,
            attachment=stem,
        )

        variants: list[PracticeAsset] = []
        for entry in self._entries_by_question().get(question_record_id, ()):
            attachment = None
            if entry.diagram_attachment_count:
                variant_record = self.catalog.variants.get_record(
                    entry.record_id,
                    (variant_catalog.IMAGE_FIELD,),
                )
                attachment = _attachment_ref(
                    variant_record.fields.get(variant_catalog.IMAGE_FIELD),
                    table_name=VARIANT_TABLE,
                    record_id=entry.record_id,
                    description="变式题题干图片",
                )
            variants.append(
                PracticeAsset(
                    source_type="variant",
                    question_id=question_id,
                    variant_id=entry.stable_id,
                    variant_number=entry.number,
                    question=entry.question,
                    answer_lines=answer_lines,
                    attachment=attachment,
                )
            )
        result = (original, tuple(variants))
        self._asset_cache[question_record_id] = result
        return result

    def load_for_student(self, student_name: str) -> PersonalPracticeData:
        self.validate_schema()
        if self._group_student_options and student_name not in self._group_student_options:
            return PersonalPracticeData(())
        group_fields = (
            "对应学生",
            "对应错题",
            "作业日期",
            "错误分类",
            "掌握状态",
            "最近再练时间",
        )
        records = self.groups.list_records(
            group_fields,
            filter_json=student_filter(student_name),
            limit=200,
        )
        evidence_by_question: dict[str, list[MistakeEvidence]] = {}
        skipped = 0
        for record in records:
            try:
                students = group_contract._student_values(record.fields.get("对应学生"))
                if student_name not in students:
                    continue
                question_links = group_contract._link_ids(record.fields.get("对应错题"))
                if len(question_links) != 1:
                    raise core.SkillError(
                        "asset_incomplete",
                        "错题记录没有唯一来源题目。",
                    )
                mastery = core._select(record.fields.get("掌握状态")) or "未开始"
                if mastery not in MASTERY_PRIORITY:
                    raise core.SkillError("asset_incomplete", "错题记录掌握状态无效。")
                category = core._select(record.fields.get("错误分类")) or "其他/待判断"
                evidence_by_question.setdefault(question_links[0], []).append(
                    MistakeEvidence(
                        mastery=mastery,
                        error_category=category,
                        assignment_date=date.fromisoformat(
                            group_contract._date_cell(record.fields.get("作业日期"))
                        ),
                        latest_retry_date=_optional_date(record.fields.get("最近再练时间")),
                    )
                )
            except core.SkillError:
                skipped += 1

        bundles: list[QuestionBundle] = []
        for question_record_id, evidence in evidence_by_question.items():
            try:
                original, variants = self._assets_for_question(question_record_id)
                bundles.append(
                    QuestionBundle(
                        original=original,
                        variants=variants,
                        evidence=tuple(evidence),
                    )
                )
            except core.SkillError:
                skipped += 1

        return PersonalPracticeData(tuple(bundles), skipped)

    def materialize_attachment(
        self,
        attachment: AttachmentRef,
        destination: Path,
    ) -> None:
        cache_key = (
            attachment.table_name,
            attachment.record_id,
            attachment.file_token,
        )
        cached = self._attachment_bytes.get(cache_key)
        if cached is not None:
            destination.write_bytes(cached)
            return
        gateway = (
            self.questions if attachment.table_name == QUESTION_TABLE else self.catalog.variants
        )
        base_token, table_id = gateway._context()
        relative_root = Path(".shi-homework2lark-downloads")
        relative_download = relative_root / f"asset-{uuid.uuid4().hex}{attachment.suffix}"
        local_download = Path.cwd() / relative_download
        relative_root.mkdir(exist_ok=True)
        try:
            self.runner.run(
                [
                    "base",
                    "+record-download-attachment",
                    "--base-token",
                    base_token,
                    "--table-id",
                    table_id,
                    "--record-id",
                    attachment.record_id,
                    "--file-token",
                    attachment.file_token,
                    "--output",
                    relative_download.as_posix(),
                    "--overwrite",
                    "--as",
                    "user",
                    "--format",
                    "json",
                ],
                retry_read=True,
            )
            if not local_download.is_file() or local_download.stat().st_size == 0:
                raise core.SkillError("attachment_download_failed", "题干图片下载失败。")
            payload = local_download.read_bytes()
            self._attachment_bytes[cache_key] = payload
            destination.write_bytes(payload)
        finally:
            local_download.unlink(missing_ok=True)
            with suppress(OSError):
                relative_root.rmdir()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a private personal-practice manifest from Lark Base"
    )
    parser.add_argument("--base-title", default=core.DEFAULT_BASE_TITLE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("schema-check")

    plan = subparsers.add_parser("plan")
    plan.add_argument("--roster", required=True)
    plan.add_argument("--student-number", required=True)
    plan.add_argument("--batch-code", required=True)
    plan.add_argument("--question-count", type=int, default=DEFAULT_QUESTION_COUNT)
    plan.add_argument("--include-mastered", action="store_true")
    plan.add_argument("--output-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        gateway = LarkPersonalPracticeGateway(
            core.SubprocessRunner(),
            base_title=args.base_title,
        )
        service = PersonalPracticeService(gateway)
        if args.command == "schema-check":
            result = service.schema_check()
        else:
            result = service.plan(
                roster_path=Path(args.roster),
                student_number=args.student_number,
                batch_code=args.batch_code,
                question_count=args.question_count,
                output_dir=Path(args.output_dir),
                include_mastered=args.include_mastered,
            )
        print(_json({"ok": True, **result}))
        return 0
    except core.SkillError as exc:
        print(_json({"ok": False, "error": {"code": exc.code, "message": exc.message}}))
        return 1
    except practice_sheet.ManifestError as exc:
        print(
            _json(
                {
                    "ok": False,
                    "error": {"code": "invalid_manifest", "message": str(exc)},
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
