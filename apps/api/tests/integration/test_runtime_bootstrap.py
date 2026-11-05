from __future__ import annotations

import importlib.util
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from tests.conftest import image_bytes


def test_fresh_local_runtime_prepares_and_accepts_vision_intake_without_ocr_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[4]
    helper = root / ".agents" / "skills" / "shi-homework2lark" / "scripts" / "runtime_service.py"
    spec = importlib.util.spec_from_file_location("runtime_bootstrap_test", helper)
    assert spec is not None and spec.loader is not None
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    database = tmp_path / "isolated-first-use.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", "")
    with socket.socket() as binding:
        binding.bind(("127.0.0.1", 0))
        port = binding.getsockname()[1]

    # Read-only checking must not create even an empty database or launch a service.
    with pytest.raises(runtime.RuntimeServiceError, match="数据库需要升级"):
        runtime.check(root, port=port)
    assert not database.exists()

    children: list[subprocess.Popen[bytes]] = []
    original_popen = subprocess.Popen

    def launch(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child = original_popen(*args, **kwargs)
        if args and isinstance(args[0], list) and "uvicorn" in args[0]:
            children.append(child)
        return child

    try:
        with patch.object(runtime.subprocess, "Popen", side_effect=launch):
            prepared = runtime.prepare(root, port=port)
            assert prepared["status"] == "ready"
            assert runtime.prepare(root, port=port)["status"] == "ready"
        assert len(children) == 1
        endpoint = f"http://127.0.0.1:{port}/api/v1"
        source = requests.post(
            f"{endpoint}/assets",
            files={"file": ("synthetic.png", image_bytes(), "image/png")},
            timeout=10,
        )
        assert source.status_code == 201, source.text
        region = requests.post(
            f"{endpoint}/assets/{source.json()['assetId']}/regions",
            json={
                "coordinateSystem": "normalized_top_left",
                "bbox": {"x": 0, "y": 0, "width": 1, "height": 1},
            },
            timeout=10,
        ).json()
        revision = requests.post(
            f"{endpoint}/regions/{region['regionId']}/revisions",
            json={
                "recognitionSource": "ai_vision",
                "correctedText": "3个苹果加2个苹果，共几个苹果？",
            },
            timeout=10,
        )
        assert revision.status_code == 201, revision.text
        record = requests.get(f"{endpoint}/problems/{region['problemId']}", timeout=10).json()
        assert record["humanRevision"]["recognitionSource"] == "ai_vision"
        assert record["history"]["ocrRuns"] == []
        # No publication: this test never accesses the user's Base or a cloud OCR.
        assert record["publication"] is None
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
