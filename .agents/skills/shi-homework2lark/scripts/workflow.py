#!/usr/bin/env python3
"""Create a homework workflow only after the teacher chooses an intake mode."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "homework-workflow-v2"


class WorkflowError(ValueError):
    """Raised when the conversational workflow contract is invalid."""


@dataclass(frozen=True)
class CollectionMode:
    mode_id: str
    number: int
    label: str
    description: str
    required_inputs: tuple[str, ...]
    identity_policy: str

    def public(self) -> dict[str, Any]:
        return {
            "id": self.mode_id,
            "number": self.number,
            "label": self.label,
            "description": self.description,
            "requiredInputs": list(self.required_inputs),
            "identityPolicy": self.identity_policy,
        }


COLLECTION_MODES = (
    CollectionMode(
        "teacher_selected",
        1,
        "教师精选",
        "发送空白卷、整页材料或单题图，由教师明确选择要收录的题。",
        ("空白卷、整页材料或单题图片", "教师选择的题目"),
        "不需要学生身份",
    ),
    CollectionMode(
        "anonymous_corrected",
        2,
        "匿名批改统计",
        "发送空白卷和已批改作业，统计错题与典型作答，但不绑定学生姓名。",
        ("空白卷", "已批改作业"),
        "不绑定姓名或学号，只保留匿名实例和人数",
    ),
    CollectionMode(
        "identified_corrected",
        3,
        "实名绑定统计",
        "发送空白卷、已批改作业和私有班级名单，按学号与姓名核对身份。",
        ("空白卷", "已批改作业", "私有学号姓名名单"),
        "私有名单校验身份，Base 默认只写姓名",
    ),
)

ALIASES: dict[str, CollectionMode] = {}
for _mode in COLLECTION_MODES:
    for _alias in (str(_mode.number), _mode.mode_id, _mode.label):
        ALIASES[_alias.casefold()] = _mode


def list_choices() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "selectionRequired": True,
        "decidedBy": "user",
        "instruction": "请选择 1、2 或 3；AI 不代替用户选择。",
        "choices": [mode.public() for mode in COLLECTION_MODES],
    }


def resolve_mode(value: str) -> CollectionMode:
    mode = ALIASES.get(value.strip().casefold())
    if mode is None:
        raise WorkflowError("collection_mode 必须由用户选择 1、2 或 3。")
    return mode


def build_state(mode_value: str) -> dict[str, Any]:
    mode = resolve_mode(mode_value)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "collectionMode": mode.mode_id,
        "collectionModeLabel": mode.label,
        "decidedBy": "user",
        "status": "awaiting_materials",
        "requiredInputs": list(mode.required_inputs),
        "identityPolicy": mode.identity_policy,
        "completedStages": [],
        "nextStage": "intake",
    }


def validate_state(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkflowError("工作流状态必须是 JSON 对象。")
    expected = {
        "schemaVersion",
        "collectionMode",
        "collectionModeLabel",
        "decidedBy",
        "status",
        "requiredInputs",
        "identityPolicy",
        "completedStages",
        "nextStage",
    }
    if set(raw) != expected:
        raise WorkflowError("工作流状态字段不完整或包含未知字段。")
    if raw.get("schemaVersion") != SCHEMA_VERSION or raw.get("decidedBy") != "user":
        raise WorkflowError("工作流必须由用户选择并使用当前版本。")
    expected_state = build_state(str(raw.get("collectionMode", "")))
    for key in (
        "collectionModeLabel",
        "requiredInputs",
        "identityPolicy",
        "nextStage",
    ):
        if raw.get(key) != expected_state[key]:
            raise WorkflowError("工作流收集方式与所需材料不一致。")
    if raw.get("status") != "awaiting_materials" or raw.get("completedStages") != []:
        raise WorkflowError("新建工作流状态无效。")
    return expected_state


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowError("无法读取工作流 JSON。") from exc


def _write_new_json(path: Path, value: object) -> None:
    destination = path.expanduser().resolve()
    if destination.exists():
        raise WorkflowError("输出文件已存在，请为新任务使用新文件名。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("choices")

    start = subparsers.add_parser("start")
    start.add_argument("--collection-mode", required=True)
    start.add_argument("--output", required=True, type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--input", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "choices":
            result = list_choices()
        elif args.command == "start":
            state = build_state(args.collection_mode)
            _write_new_json(args.output, state)
            result = {
                "started": True,
                "collectionMode": state["collectionMode"],
                "collectionModeLabel": state["collectionModeLabel"],
                "decidedBy": "user",
                "status": state["status"],
                "requiredInputs": state["requiredInputs"],
            }
        else:
            state = validate_state(_read_json(args.input))
            result = {
                "valid": True,
                "collectionMode": state["collectionMode"],
                "decidedBy": "user",
            }
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except WorkflowError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": "invalid_workflow", "message": str(exc)}},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
