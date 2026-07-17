from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mistake_notebook_api.domain.errors import JsonValue
from mistake_notebook_api.domain.publication import (
    ProblemPublicationRequest,
    ProblemPublisherError,
)
from mistake_notebook_api.infrastructure.publication.lark_cli import LarkCliProblemPublisher


def _envelope(data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {"ok": True, "data": data}


def _fields(items: dict[str, str]) -> dict[str, JsonValue]:
    return _envelope(
        {
            "fields": [
                {"id": f"fld_{index}", "name": name, "type": field_type}
                for index, (name, field_type) in enumerate(items.items())
            ]
        }
    )


class ScriptedRunner:
    def __init__(
        self,
        *,
        schema: str = "legacy",
        existing: bool = False,
        existing_by_hash: bool = False,
        duplicate: bool = False,
        duplicate_by_hash: bool = False,
        page_hash: str = "hash_1",
        sequence_values: dict[str, list[JsonValue]] | None = None,
        title_candidates: str = "legacy",
    ) -> None:
        self.schema = schema
        self.existing = existing
        self.existing_by_hash = existing_by_hash
        self.duplicate = duplicate
        self.duplicate_by_hash = duplicate_by_hash
        self.page_hash = page_hash
        self.sequence_values = sequence_values or {}
        self.title_candidates = title_candidates
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str], *, cwd: Path) -> dict[str, JsonValue]:
        assert cwd.is_absolute()
        call = tuple(args)
        self.calls.append(call)
        command = call[1]
        if command == "+title-resolve":
            if self.title_candidates != "legacy":
                candidates: list[JsonValue] = [
                    {
                        "base_token": "base_secret",
                        "title": "小学数学错题学习库",
                    },
                    {
                        "base_token": "app_wrapper",
                        "title": "小学数学错题学习库",
                    },
                ]
                return _envelope({"candidates": candidates})
            return _envelope({"base_token": "base_secret", "title": "小学数学错题学习库"})
        if command == "+table-list":
            base_token = call[call.index("--base-token") + 1]
            if base_token == "app_wrapper" and self.title_candidates != "ambiguous":
                return _envelope({"tables": []})
            names = ("错题页面", "错题题目") if self.schema == "target" else ("pages", "questions")
            return _envelope(
                {
                    "tables": [
                        {"id": "tbl_pages", "name": names[0]},
                        {"id": "tbl_questions", "name": names[1]},
                    ]
                }
            )
        if command == "+field-list":
            table_id = call[call.index("--table-id") + 1]
            if self.schema == "target":
                expected = (
                    LarkCliProblemPublisher._TARGET_PAGE_FIELDS
                    if table_id == "tbl_pages"
                    else LarkCliProblemPublisher._TARGET_QUESTION_FIELDS
                )
            else:
                expected = (
                    LarkCliProblemPublisher._LEGACY_PAGE_FIELDS
                    if table_id == "tbl_pages"
                    else LarkCliProblemPublisher._LEGACY_QUESTION_FIELDS
                )
            return _fields(expected)
        if command == "+record-list":
            table_id = call[call.index("--table-id") + 1]
            projected = [
                call[index + 1] for index, value in enumerate(call) if value == "--field-id"
            ]
            if "--filter-json" not in call:
                values = self.sequence_values.get(table_id, [])
                offset = int(call[call.index("--offset") + 1])
                limit = int(call[call.index("--limit") + 1])
                page = values[offset : offset + limit]
                return _envelope(
                    {
                        "record_id_list": [
                            f"rec_sequence_{table_id}_{offset + index}"
                            for index in range(len(page))
                        ],
                        "fields": projected,
                        "data": [[value] for value in page],
                    }
                )
            filter_json = json.loads(call[call.index("--filter-json") + 1])
            filter_field = filter_json["conditions"][0][0]
            by_hash = filter_field == "源文件哈希"
            exists = self.existing_by_hash if by_hash else self.existing
            if not exists:
                return _envelope(
                    {
                        "record_id_list": [],
                        "fields": projected,
                        "data": [],
                    }
                )
            record_id = "rec_page" if table_id == "tbl_pages" else "rec_question"
            duplicate = self.duplicate_by_hash if by_hash else self.duplicate
            ids = [record_id, f"{record_id}_duplicate"] if duplicate else [record_id]
            row = [
                (
                    [{"file_token": "file_existing"}]
                    if field in ("原始页面图片", "图片题目")
                    else self.page_hash
                    if field == "源文件哈希"
                    else "stable-id"
                )
                for field in projected
            ]
            return _envelope(
                {
                    "record_id_list": ids,
                    "fields": projected,
                    "data": [row for _ in ids],
                }
            )
        if command == "+record-upsert":
            if "--record-id" in call:
                return _envelope({"updated": True})
            table_id = call[call.index("--table-id") + 1]
            record_id = "rec_page" if table_id == "tbl_pages" else "rec_question"
            return _envelope(
                {
                    "record": {
                        "record_id_list": [record_id],
                        "fields": [],
                        "field_id_list": [],
                        "data": [[]],
                    },
                    "created": True,
                }
            )
        if command == "+record-upload-attachment":
            relative_file = call[call.index("--file") + 1]
            assert not Path(relative_file).is_absolute()
            assert (cwd / relative_file).is_file()
            return _envelope({"file_tokens": ["file_new"]})
        raise AssertionError(call)


def _request() -> ProblemPublicationRequest:
    return ProblemPublicationRequest(
        source_asset_id="asset_1",
        source_file_hash="hash_1",
        source_file_name="worksheet.png",
        source_media_type="image/png",
        source_image_bytes=b"source-bytes",
        problem_id="problem_1",
        problem_region_id="region_1",
        page_number=1,
        crop_image_bytes=b"crop-bytes",
        revision_id="revision_1",
        revision_number=2,
        corrected_text="24 支铅笔平均分给 6 人，每人多少支？",
        revision_created_at=datetime(2026, 7, 13, 2, 30, tzinfo=UTC),
        ocr_provider="paddleocr",
    )


def test_lark_cli_publisher_creates_records_and_uploads_once(tmp_path: Path) -> None:
    runner = ScriptedRunner()
    publisher = LarkCliProblemPublisher(
        runner=runner,
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    result = publisher.publish(_request())

    assert result.page_record_id == "rec_page"
    assert result.question_record_id == "rec_question"
    commands = [call[1] for call in runner.calls]
    assert commands.count("+record-upsert") == 2
    assert commands.count("+record-upload-attachment") == 2
    question_upsert = next(
        call for call in runner.calls if call[1] == "+record-upsert" and "tbl_questions" in call
    )
    body = question_upsert[question_upsert.index("--json") + 1]
    assert '"题干文本"' in body
    assert '"本地修订版本":2' in body
    assert "已审核时间" not in body
    assert "审核状态" not in body
    assert "是否待复核" not in body
    assert "标准答案" not in body
    page_upsert = next(
        call for call in runner.calls if call[1] == "+record-upsert" and "tbl_pages" in call
    )
    page_body = json.loads(page_upsert[page_upsert.index("--json") + 1])
    assert page_body == {"页面唯一ID": "asset_1", "图片名": "worksheet.png"}


def test_lark_cli_publisher_uses_readable_target_schema_and_seeds_titles(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(schema="target")
    publisher = LarkCliProblemPublisher(
        runner=runner,
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    publisher.publish(_request())

    page_call = next(
        call for call in runner.calls if call[1] == "+record-upsert" and "tbl_pages" in call
    )
    question_call = next(
        call for call in runner.calls if call[1] == "+record-upsert" and "tbl_questions" in call
    )
    page_body = json.loads(page_call[page_call.index("--json") + 1])
    question_body = json.loads(question_call[question_call.index("--json") + 1])
    assert page_body == {
        "系统页面ID": "asset_1",
        "源文件哈希": "hash_1",
        "页面名称": "待整理页面·worksheet",
    }
    assert question_body["系统题目ID"] == "problem_1"
    assert question_body["题目名称"].startswith("待整理题目·24 支铅笔平均分给 6 人")
    assert question_body["所属错题页面"] == [{"id": "rec_page"}]
    assert "图片名" not in page_body
    assert "题目唯一ID" not in question_body
    assert not any(
        call[1] == "+record-list" and "--filter-json" not in call for call in runner.calls
    )


def test_lark_cli_publisher_reuses_records_and_skips_existing_attachments(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(existing=True)
    publisher = LarkCliProblemPublisher(
        runner=runner,
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    publisher.publish(_request())

    commands = [call[1] for call in runner.calls]
    assert commands.count("+record-upsert") == 2
    assert "+record-upload-attachment" not in commands
    assert all("--record-id" in call for call in runner.calls if call[1] == "+record-upsert")


def test_lark_cli_publisher_preserves_existing_target_titles(tmp_path: Path) -> None:
    runner = ScriptedRunner(schema="target", existing=True)
    publisher = LarkCliProblemPublisher(
        runner=runner,
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    publisher.publish(_request())

    unfiltered_lists = [
        call for call in runner.calls if call[1] == "+record-list" and "--filter-json" not in call
    ]
    assert unfiltered_lists == []
    for call in runner.calls:
        if call[1] != "+record-upsert":
            continue
        body = json.loads(call[call.index("--json") + 1])
        assert "页面名称" not in body
        assert "题目名称" not in body


def test_lark_cli_publisher_reuses_target_page_by_file_hash(tmp_path: Path) -> None:
    runner = ScriptedRunner(schema="target", existing_by_hash=True)
    publisher = LarkCliProblemPublisher(
        runner=runner,
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    result = publisher.publish(_request())

    assert result.page_record_id == "rec_page"
    page_upserts = [
        call for call in runner.calls if call[1] == "+record-upsert" and "tbl_pages" in call
    ]
    assert page_upserts == []
    question_upsert = next(
        call for call in runner.calls if call[1] == "+record-upsert" and "tbl_questions" in call
    )
    question_body = json.loads(question_upsert[question_upsert.index("--json") + 1])
    assert question_body["所属错题页面"] == [{"id": "rec_page"}]
    uploads = [call for call in runner.calls if call[1] == "+record-upload-attachment"]
    assert len(uploads) == 1
    assert "tbl_questions" in uploads[0]


def test_lark_cli_publisher_rejects_duplicate_file_hashes(tmp_path: Path) -> None:
    publisher = LarkCliProblemPublisher(
        runner=ScriptedRunner(
            schema="target",
            existing_by_hash=True,
            duplicate_by_hash=True,
        ),
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    with pytest.raises(ProblemPublisherError) as captured:
        publisher.publish(_request())

    assert captured.value.category == "duplicate_remote_record"


def test_lark_cli_publisher_rejects_source_id_with_different_file_hash(
    tmp_path: Path,
) -> None:
    publisher = LarkCliProblemPublisher(
        runner=ScriptedRunner(schema="target", existing=True, page_hash="different_hash"),
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    with pytest.raises(ProblemPublisherError) as captured:
        publisher.publish(_request())

    assert captured.value.category == "invalid_response"


def test_lark_cli_publisher_rejects_duplicate_stable_ids(tmp_path: Path) -> None:
    publisher = LarkCliProblemPublisher(
        runner=ScriptedRunner(existing=True, duplicate=True),
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    with pytest.raises(ProblemPublisherError) as captured:
        publisher.publish(_request())

    assert captured.value.category == "duplicate_remote_record"


def test_lark_cli_publisher_selects_unique_schema_matching_title_candidate(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(schema="target", title_candidates="candidates")
    publisher = LarkCliProblemPublisher(
        runner=runner,
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    result = publisher.publish(_request())

    assert result.base_name == "小学数学错题学习库"
    inspected_tokens = [
        call[call.index("--base-token") + 1] for call in runner.calls if call[1] == "+table-list"
    ]
    assert inspected_tokens[:2] == ["base_secret", "app_wrapper"]


def test_lark_cli_publisher_rejects_multiple_schema_matching_title_candidates(
    tmp_path: Path,
) -> None:
    publisher = LarkCliProblemPublisher(
        runner=ScriptedRunner(schema="target", title_candidates="ambiguous"),
        base_title="小学数学错题学习库",
        working_directory=tmp_path,
    )

    with pytest.raises(ProblemPublisherError) as captured:
        publisher.publish(_request())

    assert captured.value.category == "configuration_error"
