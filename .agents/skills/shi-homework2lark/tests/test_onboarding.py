from __future__ import annotations

import base64
import gzip
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "onboarding.py"
SPEC = importlib.util.spec_from_file_location("homework_onboarding", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load onboarding module")
onboarding = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = onboarding
SPEC.loader.exec_module(onboarding)


class FakeRunner:
    def __init__(
        self,
        *,
        auth_ready: bool = True,
        base_count: int = 1,
        schema_valid: bool = True,
        table_list_fails: bool = False,
    ) -> None:
        self.auth_ready = auth_ready
        self.base_count = base_count
        self.schema_valid = schema_valid
        self.table_list_fails = table_list_fails
        self.calls: list[tuple[str, ...]] = []
        self.schema = json.loads((SKILL_ROOT / "templates" / "base-schema.json").read_text("utf-8"))
        self.views = json.loads((SKILL_ROOT / "templates" / "base-views.json").read_text("utf-8"))

    def run(
        self, args: tuple[str, ...] | list[str], *, cwd: Path | None = None
    ) -> onboarding.CommandResult:
        del cwd
        command = tuple(args)
        self.calls.append(command)
        if command[0] != "lark-cli":
            return self._result({})
        if command[1:3] == ("auth", "status"):
            status = "ready" if self.auth_ready else "missing"
            return self._result({"identities": {"user": {"status": status}}})
        operation = command[2]
        if operation == "+title-resolve":
            title = command[command.index("--title") + 1]
            candidates = [
                {"title": title, "base_token": f"base_{index + 1}"}
                for index in range(self.base_count)
            ]
            return self._envelope({"candidates": candidates})
        if operation == "+table-list":
            if self.table_list_fails:
                return self._result(
                    {"ok": False, "error": {"message": "temporary upstream failure"}},
                    returncode=1,
                )
            token = command[command.index("--base-token") + 1]
            tables = [
                {"name": table["name"], "id": f"{token}_table_{index}"}
                for index, table in enumerate(self.schema["tables"])
            ]
            if not self.schema_valid:
                tables = tables[:-1]
            return self._envelope({"tables": tables})
        if operation == "+field-list":
            token, table_index = self._table(command)
            table = self.schema["tables"][table_index]
            fields = [
                {
                    "name": field["name"],
                    "type": field["type"],
                    "id": f"{token}_f_{table_index}_{index}",
                }
                for index, field in enumerate(table["fields"])
            ]
            return self._envelope({"fields": fields})
        if operation == "+field-get":
            token, table_index = self._table(command)
            name = command[command.index("--field-id") + 1]
            table = self.schema["tables"][table_index]
            field = next(value for value in table["fields"] if value["name"] == name)
            result: dict[str, object] = {
                "name": name,
                "type": field["type"],
                "id": f"{token}_field",
            }
            source_table = field.get("sourceTable")
            if field["type"] == "link":
                source_index = self._table_index(source_table)
                result["link_table"] = f"{token}_table_{source_index}"
            if field["type"] == "lookup":
                source_index = self._table_index(source_table)
                source = self.schema["tables"][source_index]
                source_field_index = next(
                    index
                    for index, value in enumerate(source["fields"])
                    if value["name"] == field["sourceField"]
                )
                result["from"] = source_table
                result["select"] = f"{token}_f_{source_index}_{source_field_index}"
            return self._envelope({"field": result})
        if operation == "+view-list":
            _, table_index = self._table(command)
            table_name = self.schema["tables"][table_index]["name"]
            contract = next(value for value in self.views["tables"] if value["name"] == table_name)
            views = [
                {"name": value["name"], "type": value["type"], "id": f"view_{index}"}
                for index, value in enumerate(contract["views"])
            ]
            return self._envelope({"views": views})
        if operation == "+dashboard-list":
            return self._envelope({"dashboards": [{"name": "错题仪表盘"}]})
        if operation == "+view-create":
            return self._envelope({"view": {"id": "view_teaching"}})
        if operation == "+view-set-filter":
            return self._envelope({"view_id": "view_teaching"})
        if command[1:3] == ("drive", "+import"):
            return self._envelope({"base_token": "base_imported"})
        raise AssertionError(f"Unexpected command: {command}")

    def _table(self, command: tuple[str, ...]) -> tuple[str, int]:
        table_id = command[command.index("--table-id") + 1]
        for index in range(len(self.schema["tables"])):
            suffix = f"_table_{index}"
            if table_id.endswith(suffix):
                return table_id[: -len(suffix)], index
        raise AssertionError(table_id)

    def _table_index(self, name: object) -> int:
        return next(
            index for index, value in enumerate(self.schema["tables"]) if value["name"] == name
        )

    @staticmethod
    def _result(payload: object, returncode: int = 0) -> onboarding.CommandResult:
        return onboarding.CommandResult(returncode, json.dumps(payload, ensure_ascii=False), "")

    @classmethod
    def _envelope(cls, data: object) -> onboarding.CommandResult:
        return cls._result({"ok": True, "data": data})


def _repo(root: Path, *, token: str = "token-ready") -> Path:
    (root / "apps" / "api" / ".venv" / ("Scripts" if os.name == "nt" else "bin")).mkdir(
        parents=True
    )
    (root / "apps" / "api" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    python_name = "python.exe" if os.name == "nt" else "python"
    python_dir = root / "apps" / "api" / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    (python_dir / python_name).write_bytes(b"stub")
    (root / ".env.example").write_text(
        "OCR_PROVIDER=paddleocr_vl_api\nPADDLEOCR_ACCESS_TOKEN=\n"
        "REGION_DETECTION_PROVIDER=manual\nPROBLEM_PUBLISHER=lark_cli\n"
        "LARK_BASE_TITLE=小学数学错题学习库\n",
        encoding="utf-8",
    )
    if token:
        (root / ".env").write_text(f"PADDLEOCR_ACCESS_TOKEN={token}\n", encoding="utf-8")
    return root


def _service(runner: FakeRunner, *, environment: dict[str, str] | None = None):
    return onboarding.OnboardingService(
        SKILL_ROOT,
        runner=runner,
        environ=environment or {},
        which=lambda _: "available",
    )


class OnboardingStateTests(unittest.TestCase):
    def test_check_reports_first_missing_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = _service(FakeRunner())
            with self.assertRaises(onboarding.OnboardingError) as captured:
                service.check(repo_root=root, base_title="小学数学错题学习库")
            self.assertEqual(captured.exception.action, "clone_repository")

            _repo(root, token="")
            with self.assertRaises(onboarding.OnboardingError) as captured:
                service.check(repo_root=root, base_title="小学数学错题学习库")
            self.assertEqual(captured.exception.action, "configure_ocr")

    def test_check_reports_lark_auth_then_missing_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _repo(Path(temporary))
            with self.assertRaises(onboarding.OnboardingError) as captured:
                _service(FakeRunner(auth_ready=False)).check(
                    repo_root=root, base_title="小学数学错题学习库"
                )
            self.assertEqual(captured.exception.action, "authorize_lark")

            with self.assertRaises(onboarding.OnboardingError) as captured:
                _service(FakeRunner(base_count=0)).check(
                    repo_root=root, base_title="小学数学错题学习库"
                )
            self.assertEqual(captured.exception.action, "init_base")

    def test_check_ready_verifies_the_complete_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _repo(Path(temporary))
            report = _service(FakeRunner()).check(repo_root=root, base_title="小学数学错题学习库")
            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["nextAction"], "start_using")

    def test_duplicate_valid_bases_stop_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _repo(Path(temporary))
            with self.assertRaises(onboarding.OnboardingError) as captured:
                _service(FakeRunner(base_count=2)).check(
                    repo_root=root, base_title="小学数学错题学习库"
                )
            self.assertEqual(captured.exception.action, "disambiguate_base")

    def test_existing_valid_base_is_idempotent(self) -> None:
        report = _service(FakeRunner()).init_base(base_title="小学数学错题学习库")
        self.assertEqual(report["result"], "no_change")

    def test_candidate_read_failure_never_imports_a_duplicate_base(self) -> None:
        runner = FakeRunner(table_list_fails=True)
        with self.assertRaises(onboarding.OnboardingError) as captured:
            _service(runner).init_base(base_title="小学数学错题学习库")
        self.assertEqual(captured.exception.action, "authorize_lark")
        self.assertFalse(any(call[1:3] == ("drive", "+import") for call in runner.calls))


class RuntimeConfigurationTests(unittest.TestCase):
    def test_configuration_reads_secret_from_payload_without_echoing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _repo(Path(temporary), token="")
            secret = "private-paddle-token-value"
            report = _service(FakeRunner()).configure_runtime(
                repo_root=root,
                base_title="我的小学数学错题库",
                payload={"paddleocrAccessToken": secret},
                enable_yescan=False,
            )
            serialized = json.dumps(report, ensure_ascii=False)
            dotenv = (root / ".env").read_text(encoding="utf-8")
            self.assertNotIn(secret, serialized)
            self.assertIn(f"PADDLEOCR_ACCESS_TOKEN={secret}", dotenv)
            self.assertIn("REGION_DETECTION_PROVIDER=manual", dotenv)
            self.assertIn("PROBLEM_PUBLISHER=lark_cli", dotenv)

    def test_yescan_requires_both_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _repo(Path(temporary), token="")
            with self.assertRaises(onboarding.OnboardingError) as captured:
                _service(FakeRunner()).configure_runtime(
                    repo_root=root,
                    base_title="小学数学错题学习库",
                    payload={"paddleocrAccessToken": "paddle"},
                    enable_yescan=True,
                )
            self.assertEqual(captured.exception.action, "provide_yescan_key")


class TemplatePrivacyTests(unittest.TestCase):
    def test_public_contract_has_no_records_roster_remote_ids_or_legacy_fields(self) -> None:
        schema_text = (SKILL_ROOT / "templates" / "base-schema.json").read_text("utf-8")
        views_text = (SKILL_ROOT / "templates" / "base-views.json").read_text("utf-8")
        combined = schema_text + views_text
        for forbidden in (
            "records",
            "已审核时间",
            "审核状态",
            "OCR Provider",
            "生成Agent",
            "生成备注",
            "父记录",
            "2025学年",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertIsNone(onboarding.REMOTE_ID_PATTERN.search(combined))
        schema = json.loads(schema_text)
        records = next(table for table in schema["tables"] if table["name"] == "错题记录")
        students = next(field for field in records["fields"] if field["name"] == "对应学生")
        self.assertEqual(students["options"], [])

    def test_schema_only_base_has_no_records_roster_fixed_range_or_legacy_fields(self) -> None:
        package = json.loads(
            (SKILL_ROOT / "templates" / "homework2lark-empty.base").read_text("utf-8")
        )
        decoded: list[str] = []
        for value in package.values():
            if not isinstance(value, str) or len(value) < 100:
                continue
            try:
                decoded.append(gzip.decompress(base64.b64decode(value)).decode("utf-8"))
            except (ValueError, OSError, UnicodeError):
                continue
        snapshot = "\n".join(decoded)
        for table in ("错题页面", "错题题目", "错题记录", "变式题"):
            self.assertIn(table, snapshot)
        for forbidden in (
            "已审核时间",
            "审核状态",
            "OCR Provider",
            "生成Agent",
            "生成备注",
            "父记录",
            "2025学年",
            "20260717",
            "学号",
        ):
            self.assertNotIn(forbidden, snapshot)
        self.assertNotIn("recordId", snapshot)
        self.assertNotIn("record_id", snapshot)


if __name__ == "__main__":
    unittest.main()
