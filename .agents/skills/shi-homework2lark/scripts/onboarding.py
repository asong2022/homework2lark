#!/usr/bin/env python3
"""Teacher-safe installation, runtime configuration, and Base initialization."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

DEFAULT_BASE_TITLE = "小学数学错题学习库"
TEMPLATE_FILE = "templates/homework2lark-empty.base"
SCHEMA_FILE = "templates/base-schema.json"
VIEWS_FILE = "templates/base-views.json"
GRADES = frozenset(("一年级", "二年级", "三年级", "四年级", "五年级", "六年级"))
SECRET_KEYS = frozenset(("PADDLEOCR_ACCESS_TOKEN", "YESCAN_API_KEY_ID", "YESCAN_API_KEY"))
REMOTE_ID_PATTERN = re.compile(r"\b(?:app|bas|bit|blk|fld|rec|tbl|vew)[A-Za-z0-9_-]{8,}\b")


class OnboardingError(Exception):
    def __init__(self, code: str, message: str, *, action: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.retryable = retryable


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, args: Sequence[str], *, cwd: Path | None = None) -> CommandResult: ...


class SubprocessCommandRunner:
    def run(self, args: Sequence[str], *, cwd: Path | None = None) -> CommandResult:
        environment = os.environ.copy()
        environment["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        environment["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        command = list(args)
        resolved = shutil.which(command[0])
        if resolved is not None:
            command[0] = resolved
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
                shell=False,
            )
        except (FileNotFoundError, OSError) as exc:
            raise OnboardingError(
                "command_unavailable",
                "缺少初始化所需命令，请让 AI 先安装运行环境。",
                action="install_runtime",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise OnboardingError(
                "command_timeout",
                "外部服务暂时没有响应，请稍后重试。",
                action="retry",
                retryable=True,
            ) from exc
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class BaseCandidate:
    token: str
    title: str
    tables: dict[str, str]


def _public_error(error: OnboardingError) -> dict[str, JSONValue]:
    return {
        "status": "blocked",
        "code": error.code,
        "message": error.message,
        "nextAction": error.action,
        "retryable": error.retryable,
    }


def _ready(message: str, *, result: str = "ready") -> dict[str, JSONValue]:
    return {
        "status": "ready",
        "result": result,
        "message": message,
        "nextAction": "start_using",
    }


def _load_json(path: Path) -> dict[str, JSONValue]:
    try:
        decoded: JSONValue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OnboardingError(
            "template_invalid",
            "内置飞书模板不完整，请让 AI 重新安装 Skill。",
            action="reinstall_skill",
        ) from exc
    if not isinstance(decoded, dict):
        raise OnboardingError(
            "template_invalid",
            "内置飞书模板不完整，请让 AI 重新安装 Skill。",
            action="reinstall_skill",
        )
    return decoded


def _json_object(text: str, *, action: str) -> dict[str, JSONValue]:
    try:
        value: JSONValue = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OnboardingError(
            "external_response_invalid",
            "外部工具返回异常，请让 AI 检查安装状态。",
            action=action,
            retryable=True,
        ) from exc
    if not isinstance(value, dict):
        raise OnboardingError(
            "external_response_invalid",
            "外部工具返回异常，请让 AI 检查安装状态。",
            action=action,
            retryable=True,
        )
    return value


def _data(envelope: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    value = envelope.get("data")
    if not isinstance(value, dict):
        raise OnboardingError(
            "lark_response_invalid",
            "飞书返回异常，请重新授权后再试。",
            action="reauthorize_lark",
            retryable=True,
        )
    return value


def _dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _safe_env_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OnboardingError(
            "secret_missing",
            f"缺少{name}，请让 AI 引导您填写。",
            action="provide_ocr_token" if name == "PaddleOCR Token" else "provide_yescan_key",
        )
    normalized = value.strip()
    if any(character in normalized for character in ("\r", "\n", "\0")):
        raise OnboardingError(
            "secret_invalid",
            f"{name}格式不正确，请重新填写。",
            action="provide_ocr_token" if name == "PaddleOCR Token" else "provide_yescan_key",
        )
    return normalized


def _update_dotenv(path: Path, example: Path, updates: Mapping[str, str]) -> None:
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    elif example.is_file():
        lines = example.read_text(encoding="utf-8").splitlines()
    else:
        raise OnboardingError(
            "runtime_missing",
            "仓库运行配置不完整，请让 AI 重新下载仓库。",
            action="clone_repository",
        )
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    if remaining:
        if output and output[-1]:
            output.append("")
        output.extend(f"{key}={value}" for key, value in remaining.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(output).rstrip() + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _lark_json(
    runner: CommandRunner,
    skill_dir: Path,
    args: Sequence[str],
    *,
    action: str,
) -> dict[str, JSONValue]:
    result = runner.run(("lark-cli", *args), cwd=skill_dir)
    raw = result.stdout if result.returncode == 0 else result.stderr
    if result.returncode != 0:
        raise OnboardingError(
            "lark_operation_failed",
            "飞书操作未完成，请检查授权后重试。",
            action=action,
            retryable=True,
        )
    envelope = _json_object(raw, action=action)
    if envelope.get("ok") is not True:
        raise OnboardingError(
            "lark_operation_failed",
            "飞书操作未完成，请检查授权后重试。",
            action=action,
            retryable=True,
        )
    return envelope


class OnboardingService:
    def __init__(
        self,
        skill_dir: Path,
        *,
        runner: CommandRunner | None = None,
        environ: Mapping[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.skill_dir = skill_dir.resolve()
        self.runner = runner or SubprocessCommandRunner()
        self.environ = dict(os.environ if environ is None else environ)
        self.which = which
        self.schema_contract = _load_json(self.skill_dir / SCHEMA_FILE)
        self.views_contract = _load_json(self.skill_dir / VIEWS_FILE)
        self._validate_contract_privacy()

    def check(
        self,
        *,
        repo_root: Path,
        base_title: str,
        with_web: bool = False,
    ) -> dict[str, JSONValue]:
        self._check_local_runtime(repo_root, with_web=with_web)
        title = _safe_title(base_title)
        configuration = {**_dotenv(repo_root / ".env"), **self.environ}
        if not configuration.get("PADDLEOCR_ACCESS_TOKEN", "").strip():
            raise OnboardingError(
                "ocr_token_missing",
                "还缺 PaddleOCR Token；填写一次后即可长期使用。",
                action="configure_ocr",
            )
        self._check_lark_auth()
        candidates = self._resolve_candidates(title)
        if not candidates:
            raise OnboardingError(
                "base_missing",
                "飞书中还没有错题库，下一步将创建空白模板。",
                action="init_base",
            )
        candidate = self._unique_valid_candidate(candidates)
        self._verify_base(candidate)
        return _ready("配置完整，可以开始发送作业图片、PDF 或 Word 收集错题。")

    def configure_runtime(
        self,
        *,
        repo_root: Path,
        base_title: str,
        payload: Mapping[str, JSONValue],
        enable_yescan: bool,
    ) -> dict[str, JSONValue]:
        self._require_repo(repo_root)
        paddle_token = _safe_env_value(
            payload.get("paddleocrAccessToken") or self.environ.get("PADDLEOCR_ACCESS_TOKEN"),
            "PaddleOCR Token",
        )
        updates = {
            "OCR_PROVIDER": "paddleocr_vl_api",
            "PADDLEOCR_ACCESS_TOKEN": paddle_token,
            "PADDLEOCR_VL_MODEL": "PaddleOCR-VL-1.6",
            "REGION_DETECTION_PROVIDER": "yescan" if enable_yescan else "manual",
            "PROBLEM_PUBLISHER": "lark_cli",
            "LARK_BASE_TITLE": _safe_title(base_title),
        }
        if enable_yescan:
            updates["YESCAN_API_KEY_ID"] = _safe_env_value(
                payload.get("yescanApiKeyId") or self.environ.get("YESCAN_API_KEY_ID"),
                "Yescan Key ID",
            )
            updates["YESCAN_API_KEY"] = _safe_env_value(
                payload.get("yescanApiKey") or self.environ.get("YESCAN_API_KEY"),
                "Yescan Key",
            )
        _update_dotenv(repo_root / ".env", repo_root / ".env.example", updates)
        return {
            "status": "ready",
            "result": "configured",
            "message": "本机配置已保存；密钥未写入输出或仓库。",
            "nextAction": "authorize_lark",
            "configured": {
                "ocr": "PaddleOCR-VL-1.6",
                "questionSelection": "Yescan 自动候选" if enable_yescan else "教师手动框题",
                "publisher": "飞书用户身份",
            },
        }

    def init_base(
        self,
        *,
        base_title: str,
        grade: str | None = None,
        term_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, JSONValue]:
        self._check_lark_auth()
        title = _safe_title(base_title)
        range_values = (grade, term_name, start_date, end_date)
        if any(range_values) and not all(range_values):
            raise OnboardingError(
                "teaching_range_incomplete",
                "教学优先视图需要同时提供年级、学期名称和起止日期。",
                action="provide_teaching_range",
            )
        candidates = self._resolve_candidates(title)
        created = False
        if candidates:
            candidate = self._unique_valid_candidate(candidates)
            self._verify_base(candidate)
        else:
            template = self.skill_dir / TEMPLATE_FILE
            if not template.is_file():
                raise OnboardingError(
                    "template_missing",
                    "内置空白 Base 模板缺失，请重新安装 Skill。",
                    action="reinstall_skill",
                )
            envelope = _lark_json(
                self.runner,
                self.skill_dir,
                (
                    "drive",
                    "+import",
                    "--file",
                    TEMPLATE_FILE,
                    "--type",
                    "bitable",
                    "--name",
                    title,
                    "--as",
                    "user",
                    "--format",
                    "json",
                ),
                action="retry_init_base",
            )
            candidate = self._candidate_from_import(envelope, title)
            if candidate is None:
                candidates = self._resolve_candidates(title)
                candidate = self._unique_valid_candidate(candidates)
            self._verify_base(candidate)
            created = True
        if all(range_values):
            assert grade is not None
            assert term_name is not None
            assert start_date is not None
            assert end_date is not None
            self._ensure_teaching_priority_view(
                candidate,
                grade=grade,
                term_name=term_name,
                start_date=start_date,
                end_date=end_date,
            )
        return _ready(
            "空白错题库已创建并验证，可以开始使用。"
            if created
            else "现有错题库结构正确，已直接复用，没有重复创建。",
            result="created" if created else "no_change",
        )

    def verify(
        self,
        *,
        repo_root: Path,
        base_title: str,
        with_web: bool = False,
    ) -> dict[str, JSONValue]:
        return self.check(repo_root=repo_root, base_title=base_title, with_web=with_web)

    def _check_local_runtime(self, repo_root: Path, *, with_web: bool) -> None:
        self._require_repo(repo_root)
        required_commands = ["uv", "lark-cli"]
        if with_web:
            required_commands.extend(("node", "npm"))
        missing = [name for name in required_commands if not self.which(name)]
        if missing:
            raise OnboardingError(
                "runtime_command_missing",
                "运行环境还没装完整，请让 AI 自动补齐依赖。",
                action="install_runtime",
            )
        python_relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        virtual_python = repo_root / "apps" / "api" / ".venv" / python_relative
        if not virtual_python.is_file():
            raise OnboardingError(
                "api_dependencies_missing",
                "收题服务尚未安装，请让 AI 完成首次依赖安装。",
                action="install_runtime",
            )
        result = self.runner.run(
            (
                str(virtual_python),
                "-c",
                "import sys, fastapi, requests, sqlalchemy; "
                "raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 3)",
            ),
            cwd=repo_root,
        )
        if result.returncode != 0:
            raise OnboardingError(
                "api_dependencies_missing",
                "收题服务需要 Python 3.11/3.12 和完整依赖，请让 AI 修复安装。",
                action="install_runtime",
            )
        if with_web and not (repo_root / "node_modules").is_dir():
            raise OnboardingError(
                "web_dependencies_missing",
                "可视化框题页面尚未安装，请让 AI 补齐 Web 依赖。",
                action="install_web",
            )

    @staticmethod
    def _require_repo(repo_root: Path) -> None:
        if not (repo_root / "apps" / "api" / "pyproject.toml").is_file():
            raise OnboardingError(
                "repository_missing",
                "完整收题仓库尚未下载，请让 AI 先克隆公开仓库。",
                action="clone_repository",
            )

    def _check_lark_auth(self) -> None:
        result = self.runner.run(
            ("lark-cli", "auth", "status", "--json", "--verify"), cwd=self.skill_dir
        )
        if result.returncode != 0:
            raise OnboardingError(
                "lark_auth_missing",
                "飞书还未授权，请按 AI 给出的二维码或链接登录一次。",
                action="authorize_lark",
            )
        status = _json_object(result.stdout, action="authorize_lark")
        identities = status.get("identities")
        user = identities.get("user") if isinstance(identities, dict) else None
        if not isinstance(user, dict) or user.get("status") != "ready":
            raise OnboardingError(
                "lark_auth_missing",
                "飞书还未授权，请按 AI 给出的二维码或链接登录一次。",
                action="authorize_lark",
            )

    def _resolve_candidates(self, title: str) -> tuple[BaseCandidate, ...]:
        args = (
            "lark-cli",
            "base",
            "+title-resolve",
            "--title",
            title,
            "--as",
            "user",
            "--format",
            "json",
        )
        result = self.runner.run(args, cwd=self.skill_dir)
        raw = result.stdout if result.returncode == 0 else result.stderr
        envelope = _json_object(raw, action="authorize_lark")
        if result.returncode != 0 or envelope.get("ok") is not True:
            error = envelope.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            if isinstance(message, str) and message.startswith("No Base matched"):
                return ()
            raise OnboardingError(
                "lark_operation_failed",
                "飞书查询未完成，请检查授权后重试。",
                action="authorize_lark",
                retryable=True,
            )
        data = _data(envelope)
        raw_candidates: list[JSONValue]
        if isinstance(data.get("base_token"), str):
            raw_candidates = [dict(data)]
        else:
            value = data.get("candidates")
            raw_candidates = value if isinstance(value, list) else []
        candidates: list[BaseCandidate] = []
        candidate_errors: list[OnboardingError] = []
        seen: set[str] = set()
        for raw in raw_candidates:
            if not isinstance(raw, dict) or raw.get("title") != title:
                continue
            token = raw.get("base_token")
            if not isinstance(token, str) or not token or token in seen:
                continue
            seen.add(token)
            try:
                tables = self._table_map(token)
            except OnboardingError as exc:
                candidate_errors.append(exc)
                continue
            candidates.append(BaseCandidate(token, title, tables))
        if not candidates and candidate_errors:
            # A title match already exists, but its structure could not be read.
            # Never reinterpret a transient read failure as permission to import
            # another Base with the same title.
            raise candidate_errors[0]
        return tuple(candidates)

    def _table_map(self, token: str) -> dict[str, str]:
        envelope = _lark_json(
            self.runner,
            self.skill_dir,
            (
                "base",
                "+table-list",
                "--base-token",
                token,
                "--as",
                "user",
                "--limit",
                "100",
                "--format",
                "json",
            ),
            action="authorize_lark",
        )
        tables = _data(envelope).get("tables")
        if not isinstance(tables, list):
            return {}
        result: dict[str, str] = {}
        for value in tables:
            if not isinstance(value, dict):
                continue
            name, table_id = value.get("name"), value.get("id")
            if isinstance(name, str) and isinstance(table_id, str):
                result[name] = table_id
        return result

    def _candidate_from_import(
        self, envelope: Mapping[str, JSONValue], title: str
    ) -> BaseCandidate | None:
        data = _data(envelope)
        token: str | None = None
        for key in ("base_token", "token", "file_token"):
            if isinstance(data.get(key), str):
                token = str(data[key])
                break
        if token is None:
            return None
        return BaseCandidate(token, title, self._table_map(token))

    def _unique_valid_candidate(self, candidates: Sequence[BaseCandidate]) -> BaseCandidate:
        required_tables = set(self._required_tables())
        valid = [candidate for candidate in candidates if required_tables <= set(candidate.tables)]
        if len(valid) == 1:
            return valid[0]
        if len(valid) > 1:
            raise OnboardingError(
                "base_ambiguous",
                "发现多个同名错题库，AI 不能安全猜测，请先重命名其中一个。",
                action="disambiguate_base",
            )
        raise OnboardingError(
            "base_schema_conflict",
            "同名飞书 Base 不是本系统结构，请改名后再初始化。",
            action="rename_conflicting_base",
        )

    def _required_tables(self) -> tuple[str, ...]:
        raw = self.schema_contract.get("tables")
        if not isinstance(raw, list):
            return ()
        return tuple(
            value["name"]
            for value in raw
            if isinstance(value, dict) and isinstance(value.get("name"), str)
        )

    def _verify_base(self, candidate: BaseCandidate) -> None:
        table_contracts = self.schema_contract.get("tables")
        if not isinstance(table_contracts, list):
            raise OnboardingError(
                "template_invalid",
                "内置 Base 契约损坏，请重新安装 Skill。",
                action="reinstall_skill",
            )
        field_maps: dict[str, dict[str, dict[str, JSONValue]]] = {}
        id_maps: dict[str, dict[str, str]] = {}
        for table_contract in table_contracts:
            if not isinstance(table_contract, dict) or not isinstance(
                table_contract.get("name"), str
            ):
                continue
            table_name = table_contract["name"]
            table_id = candidate.tables.get(table_name)
            if table_id is None:
                self._schema_error(f"缺少数据表“{table_name}”")
            envelope = _lark_json(
                self.runner,
                self.skill_dir,
                (
                    "base",
                    "+field-list",
                    "--base-token",
                    candidate.token,
                    "--table-id",
                    table_id,
                    "--as",
                    "user",
                    "--limit",
                    "200",
                    "--format",
                    "json",
                ),
                action="repair_base_schema",
            )
            raw_fields = _data(envelope).get("fields")
            if not isinstance(raw_fields, list):
                self._schema_error(f"无法读取“{table_name}”字段")
            fields = {
                value["name"]: value
                for value in raw_fields
                if isinstance(value, dict) and isinstance(value.get("name"), str)
            }
            field_maps[table_name] = fields
            id_maps[table_name] = {
                value["id"]: value["name"]
                for value in raw_fields
                if isinstance(value, dict)
                and isinstance(value.get("id"), str)
                and isinstance(value.get("name"), str)
            }
            expected_fields = table_contract.get("fields")
            if not isinstance(expected_fields, list):
                continue
            for expected in expected_fields:
                if not isinstance(expected, dict):
                    continue
                name, field_type = expected.get("name"), expected.get("type")
                if not isinstance(name, str) or not isinstance(field_type, str):
                    continue
                actual = fields.get(name)
                if actual is None:
                    self._schema_error(f"“{table_name}”缺少字段“{name}”")
                if actual.get("type") != field_type:
                    self._schema_error(f"“{table_name}.{name}”字段类型不正确")
        for table_contract in table_contracts:
            if not isinstance(table_contract, dict) or not isinstance(
                table_contract.get("name"), str
            ):
                continue
            table_name = table_contract["name"]
            table_id = candidate.tables[table_name]
            for expected in table_contract.get("fields", []):
                if not isinstance(expected, dict) or expected.get("type") not in {"link", "lookup"}:
                    continue
                field_name = expected.get("name")
                if not isinstance(field_name, str):
                    continue
                field = self._get_field(candidate.token, table_id, field_name)
                source_table = expected.get("sourceTable")
                source_field = expected.get("sourceField")
                if field.get("type") == "link":
                    target_table_id = (
                        candidate.tables.get(source_table)
                        if isinstance(source_table, str)
                        else None
                    )
                    if target_table_id is None or field.get("link_table") != target_table_id:
                        self._schema_error(f"“{table_name}.{field_name}”关联目标不正确")
                else:
                    if not isinstance(source_table, str) or field.get("from") != source_table:
                        self._schema_error(f"“{table_name}.{field_name}”查找来源不正确")
                    selected = field.get("select")
                    if not isinstance(source_field, str) or not isinstance(selected, str):
                        self._schema_error(f"“{table_name}.{field_name}”查找字段不正确")
                    if id_maps.get(source_table, {}).get(selected) != source_field:
                        self._schema_error(f"“{table_name}.{field_name}”查找字段不正确")
        self._verify_views(candidate)

    def _get_field(self, token: str, table_id: str, field_name: str) -> dict[str, JSONValue]:
        envelope = _lark_json(
            self.runner,
            self.skill_dir,
            (
                "base",
                "+field-get",
                "--base-token",
                token,
                "--table-id",
                table_id,
                "--field-id",
                field_name,
                "--as",
                "user",
                "--format",
                "json",
            ),
            action="repair_base_schema",
        )
        field = _data(envelope).get("field")
        if not isinstance(field, dict):
            self._schema_error(f"无法读取字段“{field_name}”")
        return field

    def _verify_views(self, candidate: BaseCandidate) -> None:
        raw_tables = self.views_contract.get("tables")
        if not isinstance(raw_tables, list):
            return
        for table in raw_tables:
            if not isinstance(table, dict) or not isinstance(table.get("name"), str):
                continue
            table_name = table["name"]
            table_id = candidate.tables.get(table_name)
            if table_id is None:
                self._schema_error(f"缺少数据表“{table_name}”")
            envelope = _lark_json(
                self.runner,
                self.skill_dir,
                (
                    "base",
                    "+view-list",
                    "--base-token",
                    candidate.token,
                    "--table-id",
                    table_id,
                    "--as",
                    "user",
                    "--limit",
                    "200",
                    "--format",
                    "json",
                ),
                action="repair_base_views",
            )
            raw_views = _data(envelope).get("views")
            view_values = raw_views if isinstance(raw_views, list) else []
            names = {
                value["name"]
                for value in view_values
                if isinstance(value, dict) and isinstance(value.get("name"), str)
            }
            required_views = table.get("views")
            for view in required_views if isinstance(required_views, list) else []:
                if (
                    isinstance(view, dict)
                    and isinstance(view.get("name"), str)
                    and view["name"] not in names
                ):
                    self._schema_error(f"“{table_name}”缺少视图“{view['name']}”")
        dashboard_names = self.views_contract.get("dashboards")
        if isinstance(dashboard_names, list) and dashboard_names:
            envelope = _lark_json(
                self.runner,
                self.skill_dir,
                (
                    "base",
                    "+dashboard-list",
                    "--base-token",
                    candidate.token,
                    "--as",
                    "user",
                    "--page-size",
                    "100",
                    "--format",
                    "json",
                ),
                action="repair_base_views",
            )
            data = _data(envelope)
            raw = data.get("dashboards") or data.get("items")
            dashboard_values = raw if isinstance(raw, list) else []
            actual = {
                value["name"]
                for value in dashboard_values
                if isinstance(value, dict) and isinstance(value.get("name"), str)
            }
            for value in dashboard_names:
                if isinstance(value, str) and value not in actual:
                    self._schema_error(f"缺少仪表盘“{value}”")

    def _validate_contract_privacy(self) -> None:
        serialized = json.dumps(
            {"schema": self.schema_contract, "views": self.views_contract},
            ensure_ascii=False,
            sort_keys=True,
        )
        banned = ("已审核时间", "审核状态", "OCR Provider", "生成Agent", "生成备注", "父记录")
        if REMOTE_ID_PATTERN.search(serialized) or any(value in serialized for value in banned):
            raise OnboardingError(
                "template_privacy_invalid",
                "内置飞书模板含有不应公开的历史信息，请重新安装 Skill。",
                action="reinstall_skill",
            )
        tables = self.schema_contract.get("tables")
        if not isinstance(tables, list):
            return
        for table in tables:
            if not isinstance(table, dict) or table.get("name") != "错题记录":
                continue
            fields = table.get("fields")
            for field in fields if isinstance(fields, list) else []:
                if isinstance(field, dict) and field.get("name") == "对应学生":
                    if field.get("options") != []:
                        raise OnboardingError(
                            "template_privacy_invalid",
                            "内置飞书模板包含班级名单，请重新安装 Skill。",
                            action="reinstall_skill",
                        )
                    return
        raise OnboardingError(
            "template_invalid",
            "内置飞书模板缺少学生分组字段，请重新安装 Skill。",
            action="reinstall_skill",
        )

    def _ensure_teaching_priority_view(
        self,
        candidate: BaseCandidate,
        *,
        grade: str,
        term_name: str,
        start_date: str,
        end_date: str,
    ) -> None:
        if grade not in GRADES:
            raise OnboardingError(
                "grade_invalid", "年级应为一年级至六年级。", action="provide_teaching_range"
            )
        start = _date(start_date)
        end = _date(end_date)
        if start > end:
            raise OnboardingError(
                "date_range_invalid",
                "学期开始日期不能晚于结束日期。",
                action="provide_teaching_range",
            )
        normalized_term = term_name.strip()
        if not normalized_term or len(normalized_term) > 20:
            raise OnboardingError(
                "term_name_invalid",
                "学期名称应为 1～20 个字符。",
                action="provide_teaching_range",
            )
        table_id = candidate.tables["错题题目"]
        view_name = f"{normalized_term}·{grade}教学优先"
        envelope = _lark_json(
            self.runner,
            self.skill_dir,
            (
                "base",
                "+view-list",
                "--base-token",
                candidate.token,
                "--table-id",
                table_id,
                "--as",
                "user",
                "--limit",
                "200",
                "--format",
                "json",
            ),
            action="retry_init_base",
        )
        raw_views = _data(envelope).get("views")
        view_values = raw_views if isinstance(raw_views, list) else []
        matches = [
            value
            for value in view_values
            if isinstance(value, dict) and value.get("name") == view_name
        ]
        if len(matches) > 1:
            raise OnboardingError(
                "view_ambiguous",
                "教学优先视图重名，请先在飞书中保留一个。",
                action="disambiguate_view",
            )
        if matches:
            view_id = matches[0].get("id")
            if not isinstance(view_id, str):
                self._schema_error("教学优先视图结构异常")
        else:
            created = _lark_json(
                self.runner,
                self.skill_dir,
                (
                    "base",
                    "+view-create",
                    "--base-token",
                    candidate.token,
                    "--table-id",
                    table_id,
                    "--json",
                    json.dumps({"name": view_name, "type": "grid"}, ensure_ascii=False),
                    "--as",
                    "user",
                    "--format",
                    "json",
                ),
                action="retry_init_base",
            )
            created_data = _data(created)
            view = created_data.get("view")
            view_id = view.get("id") if isinstance(view, dict) else created_data.get("view_id")
            created_views = created_data.get("views")
            if not isinstance(view_id, str) and isinstance(created_views, list):
                first = created_views[0] if created_views else None
                view_id = first.get("id") if isinstance(first, dict) else None
            if not isinstance(view_id, str):
                self._schema_error("教学优先视图创建后无法读取")
        filter_payload = {
            "logic": "and",
            "conditions": [
                ["是否高频错题", "==", True],
                ["年级", "intersects", [grade]],
                ["时间", ">", f"ExactDate({(start - timedelta(days=1)).isoformat()})"],
                ["时间", "<", f"ExactDate({(end + timedelta(days=1)).isoformat()})"],
            ],
        }
        _lark_json(
            self.runner,
            self.skill_dir,
            (
                "base",
                "+view-set-filter",
                "--base-token",
                candidate.token,
                "--table-id",
                table_id,
                "--view-id",
                view_id,
                "--json",
                json.dumps(filter_payload, ensure_ascii=False, separators=(",", ":")),
                "--as",
                "user",
                "--format",
                "json",
            ),
            action="retry_init_base",
        )

    @staticmethod
    def _schema_error(detail: str) -> None:
        raise OnboardingError(
            "base_schema_mismatch",
            f"飞书错题库结构不完整：{detail}。",
            action="repair_base_schema",
        )


def _safe_title(value: str) -> str:
    title = value.strip()
    if not 1 <= len(title) <= 30 or any(character in title for character in ("\r", "\n", "\0")):
        raise OnboardingError(
            "base_title_invalid",
            "飞书错题库名称应为 1～30 个字符。",
            action="choose_base_title",
        )
    return title


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise OnboardingError(
            "date_invalid", "日期格式应为 YYYY-MM-DD。", action="provide_teaching_range"
        ) from exc


def _stdin_payload(enabled: bool) -> dict[str, JSONValue]:
    if not enabled:
        return {}
    try:
        value: JSONValue = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise OnboardingError(
            "stdin_invalid",
            "配置输入不是有效 JSON，请让 AI 重新提交。",
            action="configure_runtime",
        ) from exc
    if not isinstance(value, dict):
        raise OnboardingError(
            "stdin_invalid",
            "配置输入必须是 JSON 对象。",
            action="configure_runtime",
        )
    allowed = {"paddleocrAccessToken", "yescanApiKeyId", "yescanApiKey"}
    if set(value) - allowed:
        raise OnboardingError(
            "stdin_invalid",
            "配置输入含有未支持字段。",
            action="configure_runtime",
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install and initialize shi-homework2lark")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--base-title",
        default=os.environ.get("SHI_HOMEWORK2LARK_BASE_TITLE", DEFAULT_BASE_TITLE),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--with-web", action="store_true")
    configure = subparsers.add_parser("configure-runtime")
    configure.add_argument("--stdin-json", action="store_true")
    configure.add_argument("--enable-yescan", action="store_true")
    initialize = subparsers.add_parser("init-base")
    initialize.add_argument("--grade")
    initialize.add_argument("--term-name")
    initialize.add_argument("--start-date")
    initialize.add_argument("--end-date")
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
    skill_dir = Path(__file__).resolve().parent.parent
    try:
        service = OnboardingService(skill_dir)
        repo_root = Path(args.repo_root).expanduser().resolve()
        if args.command in {"check", "verify"}:
            result = getattr(service, args.command)(
                repo_root=repo_root,
                base_title=args.base_title,
                with_web=args.with_web,
            )
        elif args.command == "configure-runtime":
            result = service.configure_runtime(
                repo_root=repo_root,
                base_title=args.base_title,
                payload=_stdin_payload(args.stdin_json),
                enable_yescan=args.enable_yescan,
            )
        else:
            result = service.init_base(
                base_title=args.base_title,
                grade=args.grade,
                term_name=args.term_name,
                start_date=args.start_date,
                end_date=args.end_date,
            )
    except OnboardingError as exc:
        result = _public_error(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    secret_values = [os.environ.get(key, "") for key in SECRET_KEYS]
    if any(secret and secret in serialized for secret in secret_values):
        # This branch should be unreachable; retain a final redaction barrier.
        serialized = json.dumps(
            _public_error(
                OnboardingError(
                    "privacy_guard",
                    "输出安全检查未通过，请让 AI 更新 Skill 后重试。",
                    action="reinstall_skill",
                )
            ),
            ensure_ascii=False,
            indent=2,
        )
        print(serialized)
        return 1
    print(serialized)
    return 0


if __name__ == "__main__":
    sys.exit(main())
