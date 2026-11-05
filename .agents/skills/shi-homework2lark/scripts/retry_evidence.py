"""Read private retry facts for targeted practice; no Base writes or inference."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import homework2lark as core  # noqa: E402

RESULTS = frozenset(("correct", "partial", "incorrect", "uncertain", "not_observed"))
OBSERVABLE = frozenset(("correct", "partial", "incorrect"))
MASTERY = frozenset(("未开始", "练习中", "需再练", "已掌握"))


def _text(value: object, *, optional: bool = False) -> str:
    if value is None and optional:
        return ""
    if not isinstance(value, str) or len(value) > 20_000 or (not optional and not value.strip()):
        raise core.SkillError("invalid_retry_history", "再练历史字段不完整，未用于选题。")
    return value.strip()


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except ValueError:
        raise core.SkillError("invalid_retry_history", "再练历史时间无效。") from None


def _number(value: str) -> str:
    return str(int(value)) if value.isascii() and value.isdigit() else value


@dataclass(frozen=True)
class RetryEvidence:
    event_id: str
    question_id: str
    variant_id: str | None
    student_name: str | None
    student_number: str | None
    batch_code: str
    instance_code: str
    item_code: str
    result: str
    observed_response: str
    mark_evidence: str
    teacher_judgment: str
    mastery: str | None
    occurred_at: str

    @property
    def time(self) -> datetime:
        return _time(self.occurred_at)

    @property
    def observation_date(self) -> date:
        # Match Base assignment dates, which are interpreted in China time.
        return self.time.astimezone(timezone(timedelta(hours=8))).date()

    @property
    def selection_mastery(self) -> str | None:
        if self.result not in OBSERVABLE:
            return None
        return self.mastery or ("练习中" if self.result == "correct" else "需再练")

    def private(self) -> dict:
        return {
            "eventId": self.event_id,
            "questionId": self.question_id,
            "variantId": self.variant_id,
            "result": self.result,
            "observedResponse": self.observed_response,
            "markEvidence": self.mark_evidence,
            "teacherJudgment": self.teacher_judgment,
            "mastery": self.selection_mastery,
            "occurredAt": self.occurred_at,
        }


def parse_event(raw: object) -> RetryEvidence:
    if not isinstance(raw, dict) or raw.get("schemaVersion") not in (1, "retry-feedback-event-v1"):
        raise core.SkillError("invalid_retry_history", "再练历史版本不支持。")
    result = _text(raw.get("result"))
    mastery = raw.get("mastery")
    judgment = _text(raw.get("teacher_judgment"), optional=True)
    if result not in RESULTS or (
        mastery is not None and (not isinstance(mastery, str) or mastery not in MASTERY)
    ):
        raise core.SkillError("invalid_retry_history", "再练结果或掌握状态无效。")
    if mastery == "已掌握" and not judgment:
        raise core.SkillError("invalid_retry_history", "已掌握结论缺少教师判断。")
    identified = raw.get("schemaVersion") == "retry-feedback-event-v1"
    name = _text(raw.get("student_name"), optional=True) if identified else ""
    number = _text(raw.get("student_number"), optional=True) if identified else ""
    occurred = _text(raw.get("observed_at") or raw.get("occurred_at"))
    _time(occurred)
    return RetryEvidence(
        event_id=_text(raw.get("eventId")),
        question_id=_text(raw.get("question_id")),
        variant_id=_text(raw.get("variant_id"), optional=True) or None,
        student_name=name or None,
        student_number=number or None,
        batch_code=_text(raw.get("batch_code"), optional=True),
        instance_code=_text(raw.get("instance_code"), optional=True),
        item_code=_text(raw.get("item_code"), optional=True),
        result=result,
        observed_response=_text(raw.get("observed_response"), optional=True),
        mark_evidence=_text(raw.get("mark_evidence"), optional=True),
        teacher_judgment=judgment,
        mastery=mastery,
        occurred_at=occurred,
    )


def load_events(path: Path) -> tuple[RetryEvidence, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise core.SkillError("input_unreadable", "私有再练历史无法读取。") from None
    unique: dict[str, RetryEvidence] = {}
    for line in lines:
        if not line.strip():
            continue
        try:
            event = parse_event(json.loads(line))
        except ValueError:
            raise core.SkillError("invalid_retry_history", "再练历史不是有效 JSONL。") from None
        if event.event_id in unique and unique[event.event_id] != event:
            raise core.SkillError(
                "retry_history_conflict", "同一再练事件存在冲突内容，未重复计入。"
            )
        unique[event.event_id] = event
    return tuple(sorted(unique.values(), key=lambda event: (event.time, event.event_id)))


def for_student(
    events: Sequence[RetryEvidence], name: str, number: str
) -> tuple[RetryEvidence, ...]:
    # A supplied event store is class-scoped. Sxxx alone never identifies a student across batches.
    return tuple(
        event
        for event in events
        if event.student_name == name
        and event.student_number is not None
        and _number(event.student_number) == _number(number)
    )


def latest_by_question(
    events: Sequence[RetryEvidence], *, observable_only: bool = False
) -> dict[str, RetryEvidence]:
    latest: dict[str, RetryEvidence] = {}
    for event in sorted(events, key=lambda item: (item.time, item.event_id)):
        if not observable_only or event.result in OBSERVABLE:
            latest[event.question_id] = event
    return latest


def _counts(events: Sequence[RetryEvidence]) -> dict:
    counts = Counter(event.result for event in events)
    observed = sum(counts[name] for name in OBSERVABLE)
    return {
        "unit": "attempt",
        "attemptCount": len(events),
        "observedCount": observed,
        "correct": counts["correct"],
        "partial": counts["partial"],
        "incorrect": counts["incorrect"],
        "uncertain": counts["uncertain"],
        "notObserved": counts["not_observed"],
        "accuracy": counts["correct"] / observed if observed else None,
        "needsPracticeRate": (counts["partial"] + counts["incorrect"]) / observed
        if observed
        else None,
    }


def selection_targets(path: Path) -> dict[tuple[str, str, str, str], tuple[str, ...]]:
    paths = sorted(path.glob("students/*/selection.json")) if path.is_dir() else [path]
    if path.is_dir() and (path / "selection.json").is_file():
        paths = [path / "selection.json"]
    targets: dict[tuple[str, str, str, str], tuple[str, ...]] = {}
    try:
        for source in paths:
            report = json.loads(source.read_text(encoding="utf-8"))
            for item in report["items"]:
                categories = item.get("errorCategories") or [item["errorCategory"]]
                if not isinstance(categories, list) or not all(
                    isinstance(value, str) and value for value in categories
                ):
                    raise ValueError
                key = (
                    report["batchCode"],
                    report["student"]["instanceCode"],
                    item["itemCode"],
                    item["sourceQuestionId"],
                )
                targets[key] = tuple(dict.fromkeys(categories))
    except (OSError, ValueError, KeyError, TypeError):
        raise core.SkillError("invalid_selection", "目标错因快照无法读取，未猜测分类。") from None
    return targets


def summarize(events: Sequence[RetryEvidence], targets: Mapping | None = None) -> dict:
    unique: dict[str, RetryEvidence] = {}
    for event in events:
        if event.event_id in unique and unique[event.event_id] != event:
            raise core.SkillError(
                "retry_history_conflict", "同一再练事件存在冲突内容，未重复计入。"
            )
        unique[event.event_id] = event
    values = list(unique.values())
    questions: dict[str, list[RetryEvidence]] = {}
    causes: dict[tuple[str, str], list[RetryEvidence]] = {}
    for event in values:
        questions.setdefault(event.question_id, []).append(event)
        key = (event.batch_code, event.instance_code, event.item_code, event.question_id)
        for category in (targets or {}).get(key, ("未标注目标错因",)):
            causes.setdefault((event.question_id, category), []).append(event)
    return {
        "schemaVersion": "retry-outcomes-v1",
        **_counts(values),
        "studentCount": len(
            {
                (event.student_name, event.student_number)
                for event in values
                if event.student_name and event.student_number
            }
        ),
        "byQuestion": [
            {"questionId": key, **_counts(items)} for key, items in sorted(questions.items())
        ],
        "byTargetErrorCategory": [
            {"questionId": key[0], "errorCategory": key[1], **_counts(items)}
            for key, items in sorted(causes.items())
        ],
        "categoryNote": (
            "目标错因来自选题快照，不是对新作答的自动归因；多目标分组人数/次数不可相加。"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    core.force_utf8_stdio()
    parser = argparse.ArgumentParser(description="只读再练证据与效果汇总")
    parser.add_argument("command", choices=("context", "summary"))
    parser.add_argument("--event-store", required=True)
    parser.add_argument("--question-id")
    parser.add_argument("--roster")
    parser.add_argument("--student-number")
    parser.add_argument("--selection")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        events = load_events(Path(args.event_store))
        if bool(args.roster) != bool(args.student_number):
            raise core.SkillError("invalid_roster", "按学生读取时需同时给出私有名单和学号。")
        if args.roster:
            from personal_practice import load_roster, resolve_student

            student = resolve_student(load_roster(Path(args.roster)), args.student_number)
            events = for_student(events, student.name, student.student_number)
        if args.question_id:
            events = tuple(event for event in events if event.question_id == args.question_id)
        targets = selection_targets(Path(args.selection)) if args.selection else None
        report = (
            summarize(events, targets)
            if args.command == "summary"
            else {
                "schemaVersion": "retry-context-v1",
                "eventCount": len(events),
                "latestByQuestion": [
                    event.private() for event in latest_by_question(events).values()
                ],
                "history": [event.private() for event in events],
            }
        )
        destination = Path(args.output).expanduser().resolve()
        if destination.exists():
            raise core.SkillError("output_exists", "输出已存在，请使用新的私有文件。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        except OSError:
            raise core.SkillError(
                "output_unavailable", "私有报告无法写入，未覆盖已有文件。"
            ) from None
        print(
            json.dumps(
                {"ok": True, "eventCount": len(events), "outputWritten": True}, ensure_ascii=False
            )
        )
        return 0
    except core.SkillError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": exc.code, "message": exc.message}},
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
