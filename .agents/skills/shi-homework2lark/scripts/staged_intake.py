from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, UnidentifiedImageError

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import homework2lark as core  # noqa: E402
import personal_practice  # noqa: E402
import practice_sheet  # noqa: E402

CAMPAIGN_VERSION = "intake-campaign-v1"
BATCH_VERSION = "intake-batch-v1"
RESULT_VERSION = "intake-batch-result-v1"
EXPORT_VERSION = "intake-export-v1"
DEFAULT_MAX_PAGES_PER_BATCH = 16
MIN_MAX_PAGES_PER_BATCH = 4
MAX_MAX_PAGES_PER_BATCH = 24
MAX_TEMPLATE_PAGES = 20
SUPPORTED_IMAGE_SUFFIXES = frozenset((".jpg", ".jpeg", ".png"))
BATCH_ID_PATTERN = re.compile(r"^B\d{2,3}$")
FINDING_RESULTS = frozenset(("incorrect", "uncertain"))
CAMPAIGN_LOCK_TIMEOUT_SECONDS = 30.0
CAMPAIGN_LOCK_POLL_SECONDS = 0.05


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_json(path: Path, *, code: str, message: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise core.SkillError(code, message) from exc
    except json.JSONDecodeError as exc:
        raise core.SkillError(code, message) from exc


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_json_atomic(path: Path, value: object) -> None:
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        _write_json(temporary, value)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def _campaign_lock(campaign_dir: Path) -> Iterator[None]:
    root = campaign_dir.expanduser().resolve()
    lock_path = root / ".campaign.lock"
    try:
        stream = lock_path.open("a+b")
    except OSError as exc:
        raise core.SkillError("campaign_unreadable", "录入活动不可读取。") from exc

    with stream:
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + CAMPAIGN_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise core.SkillError(
                        "campaign_busy", "录入活动正在由另一任务更新，请稍后重试。"
                    ) from exc
                time.sleep(CAMPAIGN_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise core.SkillError("invalid_intake_input", f"{label}必须是非空文本。")
    normalized = value.strip()
    if len(normalized) > maximum or any(ord(character) < 32 for character in normalized):
        raise core.SkillError("invalid_intake_input", f"{label}格式无效。")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_image(value: object) -> tuple[Path, str, int, int, str]:
    source = Path(_text(value, "图片路径", 4096)).expanduser().resolve()
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise core.SkillError(
            "invalid_image",
            "录入页只接受 JPG、JPEG 或 PNG；PDF/Word 请先渲染为逐页图片。",
        )
    if not source.is_file():
        raise core.SkillError("input_unreadable", "录入页图片不可读取。")
    try:
        with Image.open(source) as image:
            width, height = image.size
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise core.SkillError("invalid_image", "录入页不是有效图片。") from exc
    if width <= 0 or height <= 0:
        raise core.SkillError("invalid_image", "录入页图片尺寸无效。")
    return source, suffix, width, height, _sha256(source)


def _template_pages(path: Path) -> tuple[dict[str, object], ...]:
    raw = _read_json(
        path,
        code="invalid_template",
        message="空白卷模板清单不是有效 JSON。",
    )
    if not isinstance(raw, Mapping) or set(raw) != {"pages"}:
        raise core.SkillError("invalid_template", "空白卷模板顶层只能包含 pages。")
    pages_raw = raw["pages"]
    if not isinstance(pages_raw, list) or not 1 <= len(pages_raw) <= MAX_TEMPLATE_PAGES:
        raise core.SkillError("invalid_template", "空白卷必须包含 1～20 页。")
    pages: list[dict[str, object]] = []
    for expected, value in enumerate(pages_raw, start=1):
        if not isinstance(value, Mapping) or set(value) != {"pageNumber", "path"}:
            raise core.SkillError(
                "invalid_template",
                "每个空白卷页面必须且只能包含 pageNumber 和 path。",
            )
        if value["pageNumber"] != expected:
            raise core.SkillError("invalid_template", "空白卷页码必须从 1 连续递增。")
        source, suffix, width, height, digest = _validated_image(value["path"])
        pages.append(
            {
                "pageNumber": expected,
                "source": source,
                "suffix": suffix,
                "width": width,
                "height": height,
                "sha256": digest,
            }
        )
    return tuple(pages)


def _load_campaign(campaign_dir: Path) -> tuple[Path, dict[str, object]]:
    root = campaign_dir.expanduser().resolve()
    raw = _read_json(
        root / "campaign.json",
        code="campaign_unreadable",
        message="录入活动不可读取。",
    )
    if not isinstance(raw, dict) or raw.get("manifestVersion") != CAMPAIGN_VERSION:
        raise core.SkillError("invalid_campaign", "录入活动版本或结构无效。")
    if not isinstance(raw.get("roster"), list) or not isinstance(raw.get("batches"), list):
        raise core.SkillError("invalid_campaign", "录入活动名单或批次结构无效。")
    template = raw.get("template")
    if not isinstance(template, Mapping) or not isinstance(template.get("pageCount"), int):
        raise core.SkillError("invalid_campaign", "录入活动模板结构无效。")
    return root, raw


def _campaign_roster(campaign: Mapping[str, object]) -> tuple[personal_practice.RosterStudent, ...]:
    students: list[personal_practice.RosterStudent] = []
    roster = campaign.get("roster")
    if not isinstance(roster, list):
        raise core.SkillError("invalid_campaign", "录入活动名单结构无效。")
    for value in roster:
        if not isinstance(value, Mapping):
            raise core.SkillError("invalid_campaign", "录入活动名单结构无效。")
        try:
            students.append(
                personal_practice.RosterStudent(
                    name=str(value["name"]),
                    student_number=str(value["studentNumber"]),
                    instance_code=str(value["instanceCode"]),
                )
            )
        except KeyError as exc:
            raise core.SkillError("invalid_campaign", "录入活动名单结构无效。") from exc
    return tuple(students)


def start_campaign(
    *,
    roster_path: Path,
    assignment_code: str,
    template_path: Path,
    max_pages_per_batch: int,
    output_dir: Path,
) -> dict[str, core.JSONValue]:
    practice_sheet._validate_batch_code(assignment_code)
    if isinstance(max_pages_per_batch, bool) or not (
        MIN_MAX_PAGES_PER_BATCH <= max_pages_per_batch <= MAX_MAX_PAGES_PER_BATCH
    ):
        raise core.SkillError("invalid_page_budget", "每批页数上限必须是 4～24 的整数。")
    roster = personal_practice.load_roster(roster_path)
    pages = _template_pages(template_path)
    if len(pages) > max_pages_per_batch:
        raise core.SkillError(
            "invalid_page_budget",
            "每批页数上限不能小于一名学生的完整作业页数。",
        )

    destination = output_dir.expanduser().resolve()
    if destination.exists():
        raise core.SkillError("output_exists", "录入活动目录已存在；请使用新的目录。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    working = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex[:8]}"
    working.mkdir()
    try:
        template_root = working / "template"
        template_root.mkdir()
        stored_pages: list[dict[str, object]] = []
        for page in pages:
            page_number = int(page["pageNumber"])
            suffix = str(page["suffix"])
            relative = Path("template") / f"P{page_number}{suffix}"
            shutil.copyfile(Path(page["source"]), working / relative)
            stored_pages.append(
                {
                    "pageNumber": page_number,
                    "path": relative.as_posix(),
                    "sha256": page["sha256"],
                    "width": page["width"],
                    "height": page["height"],
                }
            )
        normalized_roster = [
            {
                "instanceCode": student.instance_code,
                "studentNumber": student.student_number,
                "name": student.name,
            }
            for student in roster
        ]
        _write_json(working / "private-roster.json", {"students": normalized_roster})
        campaign = {
            "manifestVersion": CAMPAIGN_VERSION,
            "assignmentCode": assignment_code,
            "maxPagesPerBatch": max_pages_per_batch,
            "template": {"pageCount": len(pages), "pages": stored_pages},
            "roster": normalized_roster,
            "batches": [],
        }
        _write_json(working / "campaign.json", campaign)
        (working / "batches").mkdir()
        working.replace(destination)
    except Exception:
        shutil.rmtree(working, ignore_errors=True)
        raise
    return {
        "assignmentCode": assignment_code,
        "rosterStudents": len(roster),
        "templatePages": len(pages),
        "maxPagesPerBatch": max_pages_per_batch,
        "recommendedStudentsPerBatch": max_pages_per_batch // len(pages),
    }


def _submission_pages(
    value: object,
    *,
    expected_page_count: int,
) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list) or len(value) != expected_page_count:
        raise core.SkillError(
            "incomplete_student_pages",
            "每名学生必须提交与空白卷相同数量的完整页面。",
        )
    pages: list[dict[str, object]] = []
    for expected, page in enumerate(value, start=1):
        if not isinstance(page, Mapping) or set(page) != {"pageNumber", "path"}:
            raise core.SkillError(
                "invalid_batch_input",
                "学生页面必须且只能包含 pageNumber 和 path。",
            )
        if page["pageNumber"] != expected:
            raise core.SkillError(
                "incomplete_student_pages",
                "每名学生页码必须与空白卷的 1..N 完全一致。",
            )
        source, suffix, width, height, digest = _validated_image(page["path"])
        pages.append(
            {
                "pageNumber": expected,
                "source": source,
                "suffix": suffix,
                "width": width,
                "height": height,
                "sha256": digest,
            }
        )
    return tuple(pages)


def add_batch(*, campaign_dir: Path, input_path: Path) -> dict[str, core.JSONValue]:
    with _campaign_lock(campaign_dir):
        return _add_batch_locked(campaign_dir=campaign_dir, input_path=input_path)


def _add_batch_locked(*, campaign_dir: Path, input_path: Path) -> dict[str, core.JSONValue]:
    root, campaign = _load_campaign(campaign_dir)
    raw = _read_json(
        input_path,
        code="invalid_batch_input",
        message="分批录入清单不是有效 JSON。",
    )
    if not isinstance(raw, Mapping) or set(raw) != {"submissions"}:
        raise core.SkillError("invalid_batch_input", "分批录入清单顶层只能包含 submissions。")
    submissions_raw = raw["submissions"]
    if not isinstance(submissions_raw, list) or not submissions_raw:
        raise core.SkillError("invalid_batch_input", "submissions 至少包含一名学生。")

    roster = _campaign_roster(campaign)
    roster_by_number = {student.student_number: student for student in roster}
    existing_codes = {
        str(instance_code)
        for batch in campaign["batches"]
        if isinstance(batch, Mapping)
        for instance_code in batch.get("instanceCodes", [])
    }
    page_count = int(campaign["template"]["pageCount"])
    submissions: list[tuple[personal_practice.RosterStudent, tuple[dict[str, object], ...]]] = []
    selected_codes: set[str] = set()
    for value in submissions_raw:
        if not isinstance(value, Mapping) or set(value) != {"studentNumber", "pages"}:
            raise core.SkillError(
                "invalid_batch_input",
                "每份学生作业必须且只能包含 studentNumber 和 pages。",
            )
        number = _text(value["studentNumber"], "学号", 20)
        student = roster_by_number.get(number)
        if student is None:
            raise core.SkillError("student_not_found", "分批清单包含班级名单之外的学号。")
        if student.instance_code in existing_codes or student.instance_code in selected_codes:
            raise core.SkillError("duplicate_student", "同一学生不能在录入活动中重复加入。")
        selected_codes.add(student.instance_code)
        submissions.append(
            (
                student,
                _submission_pages(value["pages"], expected_page_count=page_count),
            )
        )

    total_pages = len(submissions) * page_count
    if total_pages > int(campaign["maxPagesPerBatch"]):
        raise core.SkillError(
            "batch_page_budget_exceeded",
            "本批总页数超过活动上限；请减少本批学生人数，不要拆分单个学生。",
        )
    batches = campaign["batches"]
    if not isinstance(batches, list) or len(batches) >= 999:
        raise core.SkillError("invalid_campaign", "录入活动批次数已达上限。")
    batch_id = f"B{len(batches) + 1:02d}"
    batch_root = root / "batches" / batch_id
    if batch_root.exists():
        raise core.SkillError("invalid_campaign", "下一个批次目录已存在。")
    working = root / "batches" / f".{batch_id}.tmp-{uuid.uuid4().hex[:8]}"
    working.mkdir()
    try:
        stored_students: list[dict[str, object]] = []
        for student, pages in submissions:
            stored_pages: list[dict[str, object]] = []
            student_root = working / "sources" / student.instance_code
            student_root.mkdir(parents=True)
            for page in pages:
                page_number = int(page["pageNumber"])
                suffix = str(page["suffix"])
                relative = (
                    Path("batches")
                    / batch_id
                    / "sources"
                    / student.instance_code
                    / f"P{page_number}{suffix}"
                )
                shutil.copyfile(
                    Path(page["source"]),
                    student_root / f"P{page_number}{suffix}",
                )
                stored_pages.append(
                    {
                        "pageNumber": page_number,
                        "path": relative.as_posix(),
                        "sha256": page["sha256"],
                        "width": page["width"],
                        "height": page["height"],
                    }
                )
            stored_students.append(
                {
                    "instanceCode": student.instance_code,
                    "studentNumber": student.student_number,
                    "name": student.name,
                    "pages": stored_pages,
                }
            )
        batch_manifest = {
            "manifestVersion": BATCH_VERSION,
            "assignmentCode": campaign["assignmentCode"],
            "batchId": batch_id,
            "status": "pending",
            "students": stored_students,
        }
        _write_json(working / "batch.json", batch_manifest)
        working.replace(batch_root)
        new_summary = {
            "batchId": batch_id,
            "status": "pending",
            "studentCount": len(submissions),
            "pageCount": total_pages,
            "instanceCodes": [student.instance_code for student, _ in submissions],
            "manifest": f"batches/{batch_id}/batch.json",
            "result": None,
        }
        updated = dict(campaign)
        updated["batches"] = [*batches, new_summary]
        try:
            _write_json_atomic(root / "campaign.json", updated)
        except Exception:
            shutil.rmtree(batch_root, ignore_errors=True)
            raise
    except Exception:
        shutil.rmtree(working, ignore_errors=True)
        raise
    return {
        "batchId": batch_id,
        "students": len(submissions),
        "pages": total_pages,
        "pendingBatches": sum(1 for batch in updated["batches"] if batch["status"] == "pending"),
    }


def campaign_status(*, campaign_dir: Path) -> dict[str, core.JSONValue]:
    _root, campaign = _load_campaign(campaign_dir)
    batches = campaign["batches"]
    added_codes = {
        str(code)
        for batch in batches
        if isinstance(batch, Mapping)
        for code in batch.get("instanceCodes", [])
    }
    completed_codes = {
        str(code)
        for batch in batches
        if isinstance(batch, Mapping) and batch.get("status") == "completed"
        for code in batch.get("instanceCodes", [])
    }
    return {
        "batches": len(batches),
        "pendingBatches": sum(
            1
            for batch in batches
            if isinstance(batch, Mapping) and batch.get("status") == "pending"
        ),
        "completedBatches": sum(
            1
            for batch in batches
            if isinstance(batch, Mapping) and batch.get("status") == "completed"
        ),
        "rosterStudents": len(campaign["roster"]),
        "studentsAdded": len(added_codes),
        "studentsCompleted": len(completed_codes),
        "studentsRemaining": len(campaign["roster"]) - len(added_codes),
        "pagesAdded": sum(
            int(batch.get("pageCount", 0)) for batch in batches if isinstance(batch, Mapping)
        ),
    }


def _normalize_findings(
    value: object,
    *,
    page_count: int,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise core.SkillError("invalid_batch_result", "findings 必须是列表。")
    findings: list[dict[str, object]] = []
    question_ids: set[str] = set()
    expected_fields = {
        "pageNumber",
        "questionId",
        "questionNumber",
        "observedResponse",
        "markEvidence",
        "result",
        "note",
    }
    for finding in value:
        if not isinstance(finding, Mapping) or set(finding) != expected_fields:
            raise core.SkillError(
                "invalid_batch_result",
                "每条发现字段必须严格符合已观察事实协议。",
            )
        page_number = finding["pageNumber"]
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or not (1 <= page_number <= page_count)
        ):
            raise core.SkillError("invalid_batch_result", "发现页码不在空白卷范围内。")
        question_id = _text(finding["questionId"], "题目 ID", 200)
        if question_id in question_ids:
            raise core.SkillError("duplicate_finding", "同一学生的同一道题不能重复记录。")
        question_ids.add(question_id)
        result = _text(finding["result"], "判断结果", 20)
        if result not in FINDING_RESULTS:
            raise core.SkillError(
                "invalid_batch_result",
                "判断结果只能是 incorrect 或 uncertain。",
            )
        note_value = finding["note"]
        if not isinstance(note_value, str) or len(note_value.strip()) > 1000:
            raise core.SkillError("invalid_batch_result", "备注格式无效。")
        findings.append(
            {
                "pageNumber": page_number,
                "questionId": question_id,
                "questionNumber": _text(finding["questionNumber"], "题号", 100),
                "observedResponse": _text(finding["observedResponse"], "真实作答", 2000),
                "markEvidence": _text(finding["markEvidence"], "批改证据", 1000),
                "result": result,
                "note": note_value.strip(),
            }
        )
    return findings


def complete_batch(
    *,
    campaign_dir: Path,
    batch_id: str,
    input_path: Path,
) -> dict[str, core.JSONValue]:
    with _campaign_lock(campaign_dir):
        return _complete_batch_locked(
            campaign_dir=campaign_dir,
            batch_id=batch_id,
            input_path=input_path,
        )


def _complete_batch_locked(
    *,
    campaign_dir: Path,
    batch_id: str,
    input_path: Path,
) -> dict[str, core.JSONValue]:
    if not BATCH_ID_PATTERN.fullmatch(batch_id):
        raise core.SkillError("invalid_batch_id", "批次号格式无效。")
    root, campaign = _load_campaign(campaign_dir)
    summaries = campaign["batches"]
    index = next(
        (
            position
            for position, batch in enumerate(summaries)
            if isinstance(batch, Mapping) and batch.get("batchId") == batch_id
        ),
        None,
    )
    if index is None:
        raise core.SkillError("batch_not_found", "录入活动中没有该批次。")
    batch_manifest_raw = _read_json(
        root / "batches" / batch_id / "batch.json",
        code="invalid_campaign",
        message="批次清单不可读取。",
    )
    if not isinstance(batch_manifest_raw, Mapping):
        raise core.SkillError("invalid_campaign", "批次清单结构无效。")
    batch_students = batch_manifest_raw.get("students")
    if not isinstance(batch_students, list):
        raise core.SkillError("invalid_campaign", "批次学生清单结构无效。")
    batch_by_number = {
        str(student["studentNumber"]): student
        for student in batch_students
        if isinstance(student, Mapping) and "studentNumber" in student
    }
    if len(batch_by_number) != len(batch_students):
        raise core.SkillError("invalid_campaign", "批次学生清单结构无效。")

    raw = _read_json(
        input_path,
        code="invalid_batch_result",
        message="批次处理结果不是有效 JSON。",
    )
    if not isinstance(raw, Mapping) or set(raw) != {"students"}:
        raise core.SkillError("invalid_batch_result", "批次处理结果顶层只能包含 students。")
    result_students_raw = raw["students"]
    if not isinstance(result_students_raw, list):
        raise core.SkillError("invalid_batch_result", "students 必须是列表。")
    seen_numbers: set[str] = set()
    stored_students: list[dict[str, object]] = []
    finding_count = 0
    page_count = int(campaign["template"]["pageCount"])
    for value in result_students_raw:
        if not isinstance(value, Mapping) or set(value) != {"studentNumber", "findings"}:
            raise core.SkillError(
                "invalid_batch_result",
                "每名学生结果必须且只能包含 studentNumber 和 findings。",
            )
        number = _text(value["studentNumber"], "学号", 20)
        if number in seen_numbers or number not in batch_by_number:
            raise core.SkillError(
                "invalid_batch_result",
                "结果学生集合必须与本批学生完全一致且不重复。",
            )
        seen_numbers.add(number)
        source = batch_by_number[number]
        findings = _normalize_findings(value["findings"], page_count=page_count)
        finding_count += len(findings)
        stored_students.append(
            {
                "instanceCode": source["instanceCode"],
                "studentNumber": number,
                "name": source["name"],
                "findings": findings,
            }
        )
    if seen_numbers != set(batch_by_number):
        raise core.SkillError(
            "invalid_batch_result",
            "结果学生集合必须与本批学生完全一致；全对学生也要提交空 findings。",
        )
    stored_students.sort(key=lambda student: str(student["instanceCode"]))
    result = {
        "manifestVersion": RESULT_VERSION,
        "assignmentCode": campaign["assignmentCode"],
        "batchId": batch_id,
        "students": stored_students,
    }
    result_path = root / "batches" / batch_id / "results.json"
    summary = summaries[index]
    if isinstance(summary, Mapping) and summary.get("status") == "completed":
        existing = _read_json(
            result_path,
            code="invalid_campaign",
            message="已完成批次的结果不可读取。",
        )
        if existing == result:
            return {
                "batchId": batch_id,
                "status": "no_change",
                "students": len(stored_students),
                "findings": finding_count,
            }
        raise core.SkillError(
            "batch_result_conflict",
            "该批次已经完成；不同结果不能覆盖原结果。",
        )

    _write_json_atomic(result_path, result)
    updated_summaries = list(summaries)
    updated_summary = dict(summary)
    updated_summary["status"] = "completed"
    updated_summary["result"] = f"batches/{batch_id}/results.json"
    updated_summaries[index] = updated_summary
    updated_campaign = dict(campaign)
    updated_campaign["batches"] = updated_summaries
    try:
        _write_json_atomic(root / "campaign.json", updated_campaign)
    except Exception:
        result_path.unlink(missing_ok=True)
        raise
    return {
        "batchId": batch_id,
        "status": "completed",
        "students": len(stored_students),
        "findings": finding_count,
    }


def export_results(
    *,
    campaign_dir: Path,
    output_path: Path,
) -> dict[str, core.JSONValue]:
    root, campaign = _load_campaign(campaign_dir)
    destination = output_path.expanduser().resolve()
    if destination.exists():
        raise core.SkillError("output_exists", "导出文件已存在；请使用新的文件名。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    batches = campaign["batches"]
    completed_students: list[dict[str, object]] = []
    completed_batch_ids: list[str] = []
    pending_batch_ids: list[str] = []
    added_codes: set[str] = set()
    for batch in batches:
        if not isinstance(batch, Mapping):
            raise core.SkillError("invalid_campaign", "录入活动批次结构无效。")
        batch_id = str(batch.get("batchId"))
        added_codes.update(str(code) for code in batch.get("instanceCodes", []))
        if batch.get("status") == "completed":
            result = _read_json(
                root / "batches" / batch_id / "results.json",
                code="invalid_campaign",
                message="已完成批次的结果不可读取。",
            )
            if not isinstance(result, Mapping) or not isinstance(result.get("students"), list):
                raise core.SkillError("invalid_campaign", "已完成批次的结果结构无效。")
            completed_students.extend(result["students"])
            completed_batch_ids.append(batch_id)
        else:
            pending_batch_ids.append(batch_id)
    roster_count = len(campaign["roster"])
    completed_students.sort(key=lambda student: str(student["instanceCode"]))
    export = {
        "manifestVersion": EXPORT_VERSION,
        "assignmentCode": campaign["assignmentCode"],
        "coverage": {
            "rosterStudentCount": roster_count,
            "studentsAdded": len(added_codes),
            "studentsCompleted": len(completed_students),
            "studentsNotAdded": roster_count - len(added_codes),
            "completedBatches": completed_batch_ids,
            "pendingBatches": pending_batch_ids,
            "isComplete": len(completed_students) == roster_count and not pending_batch_ids,
        },
        "students": completed_students,
    }
    _write_json_atomic(destination, export)
    return {
        "completedBatches": len(completed_batch_ids),
        "pendingBatches": len(pending_batch_ids),
        "studentsCompleted": len(completed_students),
        "studentsRemaining": roster_count - len(completed_students),
        "isComplete": export["coverage"]["isComplete"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage private staged corrected-work intake")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--roster", required=True)
    start.add_argument("--assignment-code", required=True)
    start.add_argument("--template", required=True)
    start.add_argument(
        "--max-pages-per-batch",
        type=int,
        default=DEFAULT_MAX_PAGES_PER_BATCH,
    )
    start.add_argument("--output-dir", required=True)

    add = subparsers.add_parser("add")
    add.add_argument("--campaign-dir", required=True)
    add.add_argument("--input", required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--campaign-dir", required=True)

    complete = subparsers.add_parser("complete")
    complete.add_argument("--campaign-dir", required=True)
    complete.add_argument("--batch-id", required=True)
    complete.add_argument("--input", required=True)

    export = subparsers.add_parser("export")
    export.add_argument("--campaign-dir", required=True)
    export.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            result = start_campaign(
                roster_path=Path(args.roster),
                assignment_code=args.assignment_code,
                template_path=Path(args.template),
                max_pages_per_batch=args.max_pages_per_batch,
                output_dir=Path(args.output_dir),
            )
        elif args.command == "add":
            result = add_batch(
                campaign_dir=Path(args.campaign_dir),
                input_path=Path(args.input),
            )
        elif args.command == "status":
            result = campaign_status(campaign_dir=Path(args.campaign_dir))
        elif args.command == "complete":
            result = complete_batch(
                campaign_dir=Path(args.campaign_dir),
                batch_id=args.batch_id,
                input_path=Path(args.input),
            )
        else:
            result = export_results(
                campaign_dir=Path(args.campaign_dir),
                output_path=Path(args.output),
            )
        print(_json({"ok": True, **result}))
        return 0
    except core.SkillError as exc:
        print(_json({"ok": False, "error": {"code": exc.code, "message": exc.message}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
