from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from mistake_notebook_api.api.runtime import Runtime
from mistake_notebook_api.domain.errors import AppError
from mistake_notebook_api.main import create_app


def test_unhandled_database_error_does_not_log_sql_parameters(
    runtime: Runtime, caplog: pytest.LogCaptureFixture
) -> None:
    sensitive_text = "PRIVATE_CORRECTED_TEXT_SENTINEL"
    application: FastAPI = create_app(settings=runtime.settings, runtime=runtime)

    @application.get("/_test/unhandled-database-error")
    def fail_with_sensitive_parameter() -> None:
        raise IntegrityError(
            "INSERT INTO problem_revisions (corrected_text) VALUES (?)",
            (sensitive_text,),
            Exception("constraint failed"),
        )

    assert runtime.engine.hide_parameters is True
    with (
        caplog.at_level(logging.ERROR, logger="mistake_notebook_api.api.errors"),
        TestClient(application, raise_server_exceptions=False) as client,
    ):
        response = client.get("/_test/unhandled-database-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert sensitive_text not in caplog.text
    assert "problem_revisions" not in caplog.text
    assert "exception_type=IntegrityError" in caplog.text


def test_storage_compensation_error_does_not_log_paths_or_exception_text(
    runtime: Runtime,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_path = r"E:\private\student-name\worksheet.png"

    def fail_delete(_: str) -> None:
        raise AppError("storage_unavailable", f"cannot delete {sensitive_path}")

    monkeypatch.setattr(runtime.storage, "delete", fail_delete)
    with caplog.at_level(
        logging.ERROR,
        logger="mistake_notebook_api.application.services",
    ):
        runtime.asset_service()._compensate_file("sources/current-write.png")

    assert sensitive_path not in caplog.text
    assert "cannot delete" not in caplog.text
    assert "exception_type=AppError" in caplog.text
    assert "Traceback" not in caplog.text
