from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

BUNDLE_FILE = "bundle.json"
VALID_LEVELS = ("required", "recommended", "optional")


class BundleContractError(ValueError):
    """Raised when the local bundle manifest is malformed."""


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise BundleContractError(f"{field} must be a list of non-empty strings")
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        raise BundleContractError(f"{field} contains duplicates")
    return normalized


def load_bundle(skill_dir: Path) -> dict[str, Any]:
    manifest_path = skill_dir / BUNDLE_FILE
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleContractError("bundle manifest is unreadable") from exc

    if not isinstance(raw, dict):
        raise BundleContractError("bundle manifest must be an object")
    if raw.get("schemaVersion") != "shi-skill-bundle-v1":
        raise BundleContractError("unsupported bundle schemaVersion")
    if raw.get("name") != "shi-homework2lark":
        raise BundleContractError("unexpected bundle name")
    if raw.get("entrySkill") != raw.get("name"):
        raise BundleContractError("entrySkill must match bundle name")

    dependencies = raw.get("dependencies")
    resources = raw.get("resources")
    stages = raw.get("stages")
    if not isinstance(dependencies, dict) or not isinstance(resources, dict):
        raise BundleContractError("dependencies and resources must be objects")
    if not isinstance(stages, list) or not stages:
        raise BundleContractError("stages must be a non-empty list")

    for field in (
        "requiredCommands",
        "requiredPythonModules",
        "requiredSkills",
        "recommendedSkills",
        "optionalSkills",
    ):
        _string_list(dependencies.get(field), f"dependencies.{field}")

    for field in (
        "requiredFiles",
        "includeDirectories",
        "excludeNames",
        "excludeSuffixes",
    ):
        _string_list(resources.get(field), f"resources.{field}")

    stage_ids: list[str] = []
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise BundleContractError(f"stages[{index}] must be an object")
        stage_id = stage.get("id")
        label = stage.get("label")
        if not isinstance(stage_id, str) or not stage_id:
            raise BundleContractError(f"stages[{index}].id is invalid")
        if not isinstance(label, str) or not label:
            raise BundleContractError(f"stages[{index}].label is invalid")
        stage_ids.append(stage_id)
        for field in (
            "references",
            "requiredSkills",
            "recommendedSkills",
            "optionalSkills",
            "requiredCommands",
            "requiredPythonModules",
        ):
            _string_list(stage.get(field), f"stages[{index}].{field}")
    if len(stage_ids) != len(set(stage_ids)):
        raise BundleContractError("stage ids must be unique")
    if stage_ids != ["intake", "mistakes", "variants", "practice", "feedback"]:
        raise BundleContractError("bundle must declare the five canonical stages in order")
    return raw


def default_skill_roots(skill_dir: Path) -> list[Path]:
    roots: list[Path] = [skill_dir.parent]
    configured = os.environ.get("SHI_SKILL_ROOTS", "")
    roots.extend(Path(item).expanduser() for item in configured.split(os.pathsep) if item)
    home = Path.home()
    roots.extend(
        [
            home / ".agents" / "skills",
            home / ".claude" / "skills",
            home / ".codex" / "skills",
        ]
    )
    deduplicated: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = os.path.normcase(str(root.absolute()))
        if key not in seen:
            deduplicated.append(root)
            seen.add(key)
    return deduplicated


def _skill_available(name: str, roots: Iterable[Path]) -> bool:
    return any((root / name / "SKILL.md").is_file() for root in roots)


def _command_available(name: str) -> bool:
    return shutil.which(name) is not None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _status(blocked: bool, degraded: bool) -> str:
    if blocked:
        return "blocked"
    if degraded:
        return "degraded"
    return "ready"


def build_report(
    skill_dir: Path,
    *,
    manifest: dict[str, Any] | None = None,
    skill_roots: Iterable[Path] | None = None,
    command_available: Callable[[str], bool] = _command_available,
    module_available: Callable[[str], bool] = _module_available,
) -> dict[str, Any]:
    manifest = manifest or load_bundle(skill_dir)
    roots = list(skill_roots or default_skill_roots(skill_dir))
    dependencies = manifest["dependencies"]
    resources = manifest["resources"]

    missing_files = sorted(
        item for item in resources["requiredFiles"] if not (skill_dir / item).is_file()
    )
    missing_directories = sorted(
        item for item in resources["includeDirectories"] if not (skill_dir / item).is_dir()
    )

    all_commands = sorted(
        set(dependencies["requiredCommands"])
        | {item for stage in manifest["stages"] for item in stage["requiredCommands"]}
    )
    command_checks = {name: command_available(name) for name in all_commands}

    all_modules = sorted(
        set(dependencies["requiredPythonModules"])
        | {item for stage in manifest["stages"] for item in stage["requiredPythonModules"]}
    )
    module_checks = {name: module_available(name) for name in all_modules}

    skill_levels: dict[str, str] = {}
    for level in VALID_LEVELS:
        for name in dependencies[f"{level}Skills"]:
            skill_levels[name] = level
    for stage in manifest["stages"]:
        for level in VALID_LEVELS:
            for name in stage[f"{level}Skills"]:
                current = skill_levels.get(name)
                if current is None or VALID_LEVELS.index(level) < VALID_LEVELS.index(current):
                    skill_levels[name] = level
    skill_checks = {name: _skill_available(name, roots) for name in sorted(skill_levels)}

    overall_blocked = bool(missing_files or missing_directories)
    overall_blocked = overall_blocked or any(
        not command_checks[name] for name in dependencies["requiredCommands"]
    )
    overall_blocked = overall_blocked or any(
        not module_checks[name] for name in dependencies["requiredPythonModules"]
    )
    overall_blocked = overall_blocked or any(
        not skill_checks[name] for name in dependencies["requiredSkills"]
    )
    overall_degraded = any(not skill_checks[name] for name in dependencies["recommendedSkills"])

    stage_reports: list[dict[str, Any]] = []
    for stage in manifest["stages"]:
        missing_references = sorted(
            item for item in stage["references"] if not (skill_dir / item).is_file()
        )
        missing_required = sorted(
            [
                *(f"skill:{name}" for name in stage["requiredSkills"] if not skill_checks[name]),
                *(
                    f"command:{name}"
                    for name in stage["requiredCommands"]
                    if not command_checks[name]
                ),
                *(
                    f"module:{name}"
                    for name in stage["requiredPythonModules"]
                    if not module_checks[name]
                ),
                *(f"reference:{name}" for name in missing_references),
            ]
        )
        missing_recommended = sorted(
            f"skill:{name}" for name in stage["recommendedSkills"] if not skill_checks[name]
        )
        missing_optional = sorted(
            f"skill:{name}" for name in stage["optionalSkills"] if not skill_checks[name]
        )
        stage_reports.append(
            {
                "id": stage["id"],
                "label": stage["label"],
                "status": _status(bool(missing_required), bool(missing_recommended)),
                "missingRequired": missing_required,
                "missingRecommended": missing_recommended,
                "missingOptional": missing_optional,
            }
        )

    return {
        "bundle": manifest["name"],
        "version": manifest["version"],
        "architecture": manifest["architecture"],
        "overallStatus": _status(overall_blocked, overall_degraded),
        "internalResources": {
            "status": "ready" if not missing_files and not missing_directories else "blocked",
            "missingFiles": missing_files,
            "missingDirectories": missing_directories,
        },
        "commands": [{"name": name, "available": command_checks[name]} for name in all_commands],
        "pythonModules": [{"name": name, "available": module_checks[name]} for name in all_modules],
        "skills": [
            {
                "name": name,
                "level": skill_levels[name],
                "available": skill_checks[name],
            }
            for name in sorted(skill_levels)
        ],
        "stages": stage_reports,
        "privacy": {
            "networkCalls": 0,
            "credentialValuesRead": 0,
            "filesystemPathsReported": 0,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the local shi-homework2lark bundle without network or auth."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 2 unless every required and recommended dependency is ready.",
    )
    parser.add_argument(
        "--compact", action="store_true", help="Print compact JSON instead of indented JSON."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    skill_dir = Path(__file__).resolve().parent.parent
    try:
        report = build_report(skill_dir)
    except BundleContractError as exc:
        report = {
            "bundle": "shi-homework2lark",
            "overallStatus": "blocked",
            "error": "bundle_contract_invalid",
            "message": str(exc),
            "privacy": {
                "networkCalls": 0,
                "credentialValuesRead": 0,
                "filesystemPathsReported": 0,
            },
        }
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        )
    )
    if args.strict and report["overallStatus"] != "ready":
        return 2
    return 0 if report["overallStatus"] != "blocked" else 1


if __name__ == "__main__":
    sys.exit(main())
