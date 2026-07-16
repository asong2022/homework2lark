from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import homework2lark as core  # noqa: E402
import personal_practice  # noqa: E402
import practice_sheet  # noqa: E402


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _commit_directory(working: Path, destination: Path) -> None:
    for attempt in range(6):
        try:
            os.rename(working, destination)
            return
        except PermissionError as exc:
            if attempt == 5:
                raise core.SkillError(
                    "output_commit_failed",
                    "班级练习已生成，但 Windows 持续占用新文件；临时批次已清理，请重试。",
                ) from exc
            time.sleep(0.2 * (attempt + 1))


def _select_students(
    roster: Sequence[personal_practice.RosterStudent],
    student_numbers: Sequence[str],
) -> tuple[personal_practice.RosterStudent, ...]:
    if not student_numbers:
        return tuple(roster)
    normalized = [number.strip() for number in student_numbers]
    if any(not number for number in normalized) or len(set(normalized)) != len(normalized):
        raise core.SkillError(
            "invalid_student_selection",
            "指定学号不能为空或重复。",
        )
    requested = set(normalized)
    available = {student.student_number for student in roster}
    if not requested <= available:
        raise core.SkillError(
            "student_not_found",
            "班级名单中存在无法唯一匹配的指定学号。",
        )
    return tuple(student for student in roster if student.student_number in requested)


class ClassPracticeService:
    def __init__(
        self,
        personal_service: personal_practice.PersonalPracticeService,
        *,
        document_builder: Callable[[Path, Path], None] = practice_sheet.build_document,
    ) -> None:
        self.personal_service = personal_service
        self.document_builder = document_builder

    def schema_check(self) -> dict[str, core.JSONValue]:
        result = self.personal_service.schema_check()
        return {**result, "classPractice": "ready"}

    def build(
        self,
        *,
        roster_path: Path,
        batch_code: str,
        question_count: int,
        output_dir: Path,
        include_mastered: bool = False,
        student_numbers: Sequence[str] = (),
    ) -> dict[str, core.JSONValue]:
        practice_sheet._validate_batch_code(batch_code)
        if isinstance(question_count, bool) or not (
            personal_practice.MIN_QUESTION_COUNT
            <= question_count
            <= personal_practice.MAX_QUESTION_COUNT
        ):
            raise core.SkillError(
                "invalid_question_count",
                "题量必须是 1～12 的整数。",
            )
        roster = personal_practice.load_roster(roster_path)
        students = _select_students(roster, student_numbers)

        destination = output_dir.expanduser().resolve()
        if destination.exists():
            raise core.SkillError(
                "output_exists",
                "输出目录已存在；请为本次班级练习使用新的目录。",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        working = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex[:8]}"
        working.mkdir()

        rows: list[dict[str, object]] = []
        generated = 0
        total_selected = 0
        try:
            students_root = working / "students"
            students_root.mkdir()
            for student in students:
                student_dir = students_root / student.instance_code
                try:
                    result = self.personal_service.plan(
                        roster_path=roster_path,
                        student_number=student.student_number,
                        batch_code=batch_code,
                        question_count=question_count,
                        output_dir=student_dir,
                        include_mastered=include_mastered,
                    )
                except core.SkillError as exc:
                    if exc.code != "no_eligible_questions":
                        raise
                    rows.append(
                        {
                            "instanceCode": student.instance_code,
                            "studentNumber": student.student_number,
                            "name": student.name,
                            "status": "no_eligible_items",
                            "selected": 0,
                            "worksheet": None,
                        }
                    )
                    continue

                worksheet_name = f"{student.instance_code}-个人练习纸.docx"
                self.document_builder(
                    student_dir / "manifest.json",
                    student_dir / worksheet_name,
                )
                selected = int(result["selected"])
                generated += 1
                total_selected += selected
                rows.append(
                    {
                        "instanceCode": student.instance_code,
                        "studentNumber": student.student_number,
                        "name": student.name,
                        "status": "generated",
                        "selected": selected,
                        "worksheet": f"students/{student.instance_code}/{worksheet_name}",
                    }
                )

            summary = {
                "manifestVersion": "class-personal-practice-v2",
                "batchCode": batch_code,
                "layout": "word_auto_flow",
                "requestedQuestionCount": question_count,
                "includeMastered": include_mastered,
                "rosterStudentCount": len(roster),
                "requestedStudentCount": len(students),
                "generatedStudentCount": generated,
                "noEligibleStudentCount": len(students) - generated,
                "selectedQuestionCount": total_selected,
                "students": rows,
            }
            _write_json(working / "batch-summary.json", summary)
            with (working / "班级个人练习清单.csv").open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "instanceCode",
                        "studentNumber",
                        "name",
                        "status",
                        "selected",
                        "worksheet",
                    ),
                )
                writer.writeheader()
                writer.writerows(rows)
            _commit_directory(working, destination)
        except Exception:
            shutil.rmtree(working, ignore_errors=True)
            raise

        return {
            "rosterStudents": len(roster),
            "requestedStudents": len(students),
            "generatedStudents": generated,
            "studentsWithoutEligibleItems": len(students) - generated,
            "worksheets": generated,
            "selectedQuestions": total_selected,
            "layout": "word_auto_flow",
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build private personalized worksheets for a class roster"
    )
    parser.add_argument("--base-title", default=core.DEFAULT_BASE_TITLE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("schema-check")

    build = subparsers.add_parser("build")
    build.add_argument("--roster", required=True)
    build.add_argument("--batch-code", required=True)
    build.add_argument(
        "--question-count",
        type=int,
        default=personal_practice.DEFAULT_QUESTION_COUNT,
    )
    build.add_argument("--include-mastered", action="store_true")
    build.add_argument("--student-number", action="append", default=[])
    build.add_argument("--output-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        gateway = personal_practice.LarkPersonalPracticeGateway(
            core.SubprocessRunner(),
            base_title=args.base_title,
        )
        service = ClassPracticeService(personal_practice.PersonalPracticeService(gateway))
        if args.command == "schema-check":
            result = service.schema_check()
        else:
            result = service.build(
                roster_path=Path(args.roster),
                batch_code=args.batch_code,
                question_count=args.question_count,
                output_dir=Path(args.output_dir),
                include_mastered=args.include_mastered,
                student_numbers=args.student_number,
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
