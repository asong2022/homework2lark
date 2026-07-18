#!/usr/bin/env python3
"""Plan and validate image/PDF/Word source normalization for Agent intake."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

IMAGE_SUFFIXES = frozenset((".jpg", ".jpeg", ".png"))
PDF_SUFFIXES = frozenset((".pdf",))
WORD_SUFFIXES = frozenset((".doc", ".docx"))
STRUCTURED_SUFFIXES = frozenset((".md", ".json", ".html"))

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]


class SourceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def plan_source(path: Path) -> dict[str, JSONValue]:
    if not path.is_file():
        raise SourceError("input_unreadable", "找不到要处理的作业材料。")
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        source_type = "image"
        route = "image_intake"
        steps = ["single_or_whole_page_decision", "chat_or_web_or_single"]
        third_party = ["yescan_when_chat_selected", "paddleocr_vl_after_region_saved"]
    elif suffix in PDF_SUFFIXES:
        source_type = "pdf"
        route = "mineru_plus_pdf_page_render"
        steps = ["privacy_notice", "mineru_structure", "render_selected_pages", "validate_bundle"]
        third_party = ["mineru", "yescan_when_chat_selected", "paddleocr_vl_after_region_saved"]
    elif suffix in WORD_SUFFIXES:
        source_type = "word"
        route = "doc_render_plus_optional_mineru"
        steps = [
            "privacy_notice",
            "render_word_to_pdf_pages",
            "optional_mineru_structure",
            "validate_bundle",
        ]
        third_party = [
            "mineru_when_used",
            "yescan_when_chat_selected",
            "paddleocr_vl_after_region_saved",
        ]
    else:
        raise SourceError(
            "unsupported_source_type", "材料必须是 JPG、JPEG、PNG、PDF、DOC 或 DOCX。"
        )
    return {
        "sourceType": source_type,
        "fileName": path.name,
        "route": route,
        "steps": steps,
        "possibleThirdParties": third_party,
        "directFastApiUpload": source_type == "image",
    }


def validate_bundle(raw: JSONValue) -> dict[str, JSONValue]:
    bundle = _object(raw, "SourceBundle")
    allowed = {
        "schemaVersion",
        "sourceType",
        "originalFileName",
        "privacyNoticeShown",
        "pages",
    }
    if set(bundle) - allowed:
        raise SourceError("invalid_bundle", "SourceBundle 包含未支持或私密字段。")
    if bundle.get("schemaVersion") != 1:
        raise SourceError("invalid_bundle", "schemaVersion 必须为 1。")
    source_type = bundle.get("sourceType")
    if source_type not in {"image", "pdf", "word"}:
        raise SourceError("invalid_bundle", "sourceType 必须是 image、pdf 或 word。")
    file_name = bundle.get("originalFileName")
    if not isinstance(file_name, str) or not file_name or Path(file_name).name != file_name:
        raise SourceError("invalid_bundle", "originalFileName 只能是文件名，不能包含路径。")
    if bundle.get("privacyNoticeShown") is not True:
        raise SourceError("privacy_notice_required", "远程处理前必须先向教师说明数据流向。")
    raw_pages = bundle.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise SourceError("invalid_bundle", "pages 必须至少包含一页视觉证据。")
    pages: list[dict[str, JSONValue]] = []
    seen: set[int] = set()
    for item in raw_pages:
        page = _object(item, "page")
        if set(page) - {"pageNumber", "pageImagePath", "structuredTextPath"}:
            raise SourceError("invalid_bundle", "page 包含未支持字段。")
        number = page.get("pageNumber")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1 or number in seen:
            raise SourceError("invalid_bundle", "pageNumber 必须是唯一正整数。")
        seen.add(number)
        image_path = _relative_existing_file(
            page.get("pageImagePath"), IMAGE_SUFFIXES, "pageImagePath"
        )
        structured_value = page.get("structuredTextPath")
        structured_path: str | None = None
        if structured_value not in (None, ""):
            structured_path = _relative_existing_file(
                structured_value, STRUCTURED_SUFFIXES, "structuredTextPath"
            )
        pages.append(
            {
                "pageNumber": number,
                "pageImagePath": image_path,
                "structuredTextPath": structured_path,
            }
        )
    pages.sort(key=lambda value: int(value["pageNumber"]))
    return {
        "schemaVersion": 1,
        "sourceType": source_type,
        "originalFileName": file_name,
        "privacyNoticeShown": True,
        "pageCount": len(pages),
        "pages": pages,
        "next": "send_each_page_to_chat_or_web_selection",
    }


def _relative_existing_file(value: JSONValue, suffixes: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceError("invalid_bundle", f"{label} 必须是相对文件路径。")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise SourceError("unsafe_path", f"{label} 必须位于当前工作目录内。")
    resolved = (Path.cwd() / path).resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise SourceError("unsafe_path", f"{label} 超出当前工作目录。")
    if resolved.suffix.lower() not in suffixes or not resolved.is_file():
        raise SourceError("bundle_file_missing", f"{label} 文件不存在或格式无效。")
    return str(path).replace("\\", "/")


def _object(value: JSONValue, label: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise SourceError("invalid_bundle", f"{label} 必须是对象。")
    return value


def load_json(path_value: str) -> JSONValue:
    if path_value == "-":
        content = sys.stdin.read()
    else:
        path = Path(path_value)
        if path.is_absolute() or ".." in path.parts:
            raise SourceError("unsafe_path", "manifest 必须位于当前工作目录内。")
        try:
            content = (Path.cwd() / path).resolve().read_text(encoding="utf-8")
        except OSError as exc:
            raise SourceError("input_unreadable", "无法读取 SourceBundle。") from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise SourceError("invalid_bundle", "SourceBundle 不是有效 JSON。") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--file", required=True, type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--input", required=True)
    return parser


def _force_utf8_stdio() -> None:
    """Windows 控制台/管道默认 GBK；AI 消费的中文 JSON 必须始终按 UTF-8 输出。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        result = (
            plan_source(args.file)
            if args.command == "plan"
            else validate_bundle(load_json(args.input))
        )
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except SourceError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": exc.code, "message": exc.message}},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
