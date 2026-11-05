"""Prepare/probe the existing local evidence API; never touches Lark or OCR."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


class RuntimeServiceError(Exception):
    def __init__(self, code: str, message: str, action: str = "prepare_runtime") -> None:
        super().__init__(message)
        self.code, self.message, self.action = code, message, action


def _python(repo: Path) -> Path:
    binary = (
        repo
        / "apps"
        / "api"
        / ".venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    if not binary.is_file():
        raise RuntimeServiceError(
            "api_dependencies_missing", "收题环境尚未安装，请让 AI 补齐。", "install_runtime"
        )
    return binary


def _command(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(_python(repo)), "-X", "utf8", *args],
            cwd=repo / "apps" / "api",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeServiceError(
            "runtime_unavailable", "本地收题服务检查未完成，请让 AI 修复后重试。"
        ) from None


def _database_probe(repo: Path) -> dict:
    # Runs only in the repository's managed API interpreter, without writing a database.
    sys.path.insert(0, str(repo / "apps" / "api" / "src"))
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import make_url

    from mistake_notebook_api.config import get_settings, runtime_identity

    settings = get_settings()
    heads = set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
    url = make_url(settings.database_url)
    exists = url.get_backend_name() != "sqlite" or bool(
        url.database and url.database != ":memory:" and Path(url.database).is_file()
    )
    current: set[str] = set()
    if exists:
        engine = create_engine(settings.database_url, hide_parameters=True)
        try:
            with engine.connect() as connection:
                tables = set(inspect(connection).get_table_names())
                if "alembic_version" in tables:
                    current = set(
                        connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        ).scalars()
                    )
                if not {"source_assets", "problem_assets", "problem_revisions"}.issubset(tables):
                    current = set()
        finally:
            engine.dispose()
    pdf = (
        any(importlib.util.find_spec(name) is not None for name in ("pypdfium2", "fitz"))
        or shutil.which("pdftoppm") is not None
    )
    word = bool(shutil.which("soffice") or shutil.which("libreoffice"))
    return {
        "migrations": "current" if current == heads else "pending",
        "runtimeId": runtime_identity(settings),
        "capabilities": {
            "imageIntake": "ready",
            "practiceWord": "ready"
            if importlib.util.find_spec("docx") is not None
            else "requires_setup",
            "pdf": "ready" if pdf else "requires_agent_renderer",
            "word": "ready" if word else "requires_agent_renderer",
        },
    }


def _probe(repo: Path) -> dict:
    result = _command(repo, [str(Path(__file__).resolve()), "probe-db", "--repo-root", str(repo)])
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        payload = None
    if result.returncode != 0 or not isinstance(payload, dict) or "runtimeId" not in payload:
        raise RuntimeServiceError(
            "database_probe_failed", "本地数据库尚未就绪，请让 AI 准备或修复收题环境。"
        )
    return payload


def _health(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/health", timeout=2
        ) as response:
            value = json.load(response)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _matches(health: dict | None, state: dict) -> bool:
    return bool(
        health
        and health.get("status") == "ok"
        and health.get("database") == "ok"
        and health.get("runtimeId") == state.get("runtimeId")
    )


def check(repo_root: Path, *, port: int = 8000) -> dict:
    repo = repo_root.resolve()
    state = _probe(repo)
    if state.get("migrations") != "current":
        raise RuntimeServiceError(
            "database_migration_pending", "数据库需要升级；请让 AI 自动准备收题服务。"
        )
    if not _matches(_health(port), state):
        raise RuntimeServiceError(
            "api_not_ready", "收题服务尚未启动或不是本仓库的服务，请让 AI 准备。"
        )
    return {
        "status": "ready",
        "database": "current",
        "api": "ready",
        "capabilities": state["capabilities"],
    }


def prepare(repo_root: Path, *, port: int = 8000) -> dict:
    repo = repo_root.resolve()
    state = _probe(repo)
    healthy = _health(port)
    if _matches(healthy, state) and state.get("migrations") == "current":
        return check(repo, port=port)
    # A service on this port is not ours to terminate or migrate underneath.
    try:
        occupied = socket.create_connection(("127.0.0.1", port), timeout=0.5)
    except OSError:
        occupied = None
    if occupied is not None:
        occupied.close()
        raise RuntimeServiceError(
            "runtime_port_in_use",
            "端口已有服务，请让 AI 确认并重启对应收题服务；没有终止其他进程。",
            "inspect_runtime",
        )
    if state.get("migrations") != "current":
        result = _command(repo, ["-m", "alembic", "upgrade", "head"])
        if result.returncode != 0:
            raise RuntimeServiceError(
                "database_migration_failed", "数据库升级未完成，原有材料已保留，请让 AI 诊断。"
            )
        state = _probe(repo)
        if state.get("migrations") != "current":
            raise RuntimeServiceError(
                "database_migration_failed", "数据库尚未达到当前版本，请让 AI 诊断。"
            )
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        process = subprocess.Popen(
            [
                str(_python(repo)),
                "-X",
                "utf8",
                "-m",
                "uvicorn",
                "--app-dir",
                "src",
                "mistake_notebook_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=repo / "apps" / "api",
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **options,
        )
    except OSError:
        raise RuntimeServiceError(
            "api_start_failed", "收题服务未能启动，请让 AI 检查依赖。"
        ) from None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _matches(_health(port), state):
            return check(repo, port=port)
        if process.poll() is not None:
            break
        time.sleep(0.25)
    if process.poll() is None:
        process.terminate()  # Only the process started by this invocation.
    raise RuntimeServiceError(
        "api_start_failed", "收题服务启动后未就绪；本次启动已停止，材料未改动。"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="本地收题服务准备和只读检查")
    parser.add_argument("command", choices=("check", "prepare", "probe-db"))
    parser.add_argument("--repo-root", required=True)
    parser.add_argument(
        "--port", type=int, default=8000, choices=range(1024, 65536), metavar="PORT"
    )
    args = parser.parse_args()
    try:
        repo = Path(args.repo_root).expanduser().resolve()
        result = (
            _database_probe(repo)
            if args.command == "probe-db"
            else globals()[args.command](repo, port=args.port)
        )
    except RuntimeServiceError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "code": exc.code,
                    "message": exc.message,
                    "nextAction": exc.action,
                },
                ensure_ascii=False,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "code": "runtime_unavailable",
                    "message": "本地服务检查失败，请让 AI 修复。",
                    "nextAction": "prepare_runtime",
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
