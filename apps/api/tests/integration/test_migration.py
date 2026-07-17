from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from mistake_notebook_api.config import get_settings

EXPECTED_TABLES = {
    "alembic_version",
    "source_assets",
    "region_detection_runs",
    "region_candidates",
    "problem_regions",
    "problem_region_candidate_sources",
    "ocr_runs",
    "problem_revisions",
    "problem_publications",
    "problem_assets",
}


def test_migration_up_down_up(tmp_path: Path, monkeypatch: object) -> None:
    database = tmp_path / "migration.db"
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(database_url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    engine.dispose()
    get_settings.cache_clear()


def test_multi_candidate_migration_backfills_existing_primary_candidate(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    database = tmp_path / "backfill.db"
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    command.upgrade(config, "0002_region_detection")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_assets "
                "(id, file_name, media_type, storage_key, file_hash, width, height, "
                "file_size, created_at) VALUES "
                "('asset_old', 'old.png', 'image/png', 'sources/old.png', 'hash', "
                "100, 100, 100, '2026-07-12 08:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO region_detection_runs "
                "(id, source_asset_id, provider, provider_model, provider_version, status, "
                "error_code, raw_response_storage_key, warnings_json, started_at, finished_at, "
                "processing_time_ms) VALUES "
                "('detection_old', 'asset_old', 'fake', 'fixture', '1', 'succeeded', NULL, "
                "'provider-evidence/old.json', '[]', '2026-07-12 08:00:00', "
                "'2026-07-12 08:00:01', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO region_candidates "
                "(id, detection_run_id, provider_candidate_id, x, y, width, height, "
                "coordinate_system, confidence, reading_order, metadata_json, created_at) "
                "VALUES ('candidate_old', 'detection_old', 'provider-old', 10, 10, 50, 40, "
                "'pixel_top_left', 0.9, 0, '{}', '2026-07-12 08:00:01')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO problem_regions "
                "(id, source_asset_id, page_number, x, y, width, height, coordinate_system, "
                "cropped_asset_key, created_at, selection_source, detection_candidate_id) "
                "VALUES ('region_old', 'asset_old', 1, 10, 10, 50, 40, 'pixel_top_left', "
                "'crops/old.png', '2026-07-12 08:00:02', 'detected', 'candidate_old')"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT problem_region_id, detection_candidate_id, source_order "
                "FROM problem_region_candidate_sources"
            )
        ).all()
    engine.dispose()
    assert rows == [("region_old", "candidate_old", 0)]
    get_settings.cache_clear()


def test_problem_asset_migration_preserves_existing_lineage_and_publication(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    database = tmp_path / "problem-assets.db"
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    command.upgrade(config, "0004_problem_publications")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_assets "
                "(id, file_name, media_type, storage_key, file_hash, width, height, "
                "file_size, created_at) VALUES "
                "('asset_preserved', 'page.png', 'image/png', 'sources/page.png', "
                "'hash-preserved', 1200, 1600, 2048, '2026-07-16 08:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO problem_regions "
                "(id, source_asset_id, page_number, x, y, width, height, coordinate_system, "
                "cropped_asset_key, created_at, selection_source, detection_candidate_id) "
                "VALUES ('region_preserved', 'asset_preserved', 1, 10, 20, 800, 500, "
                "'pixel_top_left', 'crops/problem.png', '2026-07-16 08:01:00', "
                "'manual', NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ocr_runs "
                "(id, problem_region_id, provider, provider_model, provider_version, "
                "raw_response, extracted_text, confidence, blocks_json, warnings_json, "
                "status, error_code, started_at, finished_at, processing_time_ms) VALUES "
                "('ocr_preserved', 'region_preserved', 'paddleocr_vl_api', "
                "'PaddleOCR-VL-1.6', 'api-v2', '{}', '机器识别文本', 0.95, '[]', '[]', "
                "'succeeded', NULL, '2026-07-16 08:02:00', "
                "'2026-07-16 08:02:03', 3000)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO problem_revisions "
                "(id, problem_region_id, based_on_ocr_run_id, revision_number, "
                "corrected_text, correction_note, created_at) VALUES "
                "('revision_preserved', 'region_preserved', 'ocr_preserved', 1, "
                "'教师确认后的完整题目', '修正 OCR', '2026-07-16 08:03:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO reviewed_problems "
                "(id, problem_region_id, current_revision_id, review_status, reviewed_at, "
                "created_at, updated_at) VALUES "
                "('problem_preserved', 'region_preserved', 'revision_preserved', "
                "'reviewed', '2026-07-16 08:04:00', '2026-07-16 08:01:00', "
                "'2026-07-16 08:04:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO review_status_events "
                "(id, reviewed_problem_id, from_status, to_status, reason, ocr_run_id, "
                "revision_id, created_at) VALUES "
                "('review_event_preserved', 'problem_preserved', 'needs_review', "
                "'reviewed', 'teacher_confirmed', 'ocr_preserved', "
                "'revision_preserved', '2026-07-16 08:04:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO problem_publications "
                "(id, reviewed_problem_id, source_asset_id, publisher, status, "
                "published_revision_id, base_name, pages_table_id, questions_table_id, "
                "page_record_id, question_record_id, error_code, started_at, finished_at, "
                "updated_at) VALUES "
                "('publication_preserved', 'problem_preserved', 'asset_preserved', "
                "'lark_cli', 'succeeded', 'revision_preserved', '小学数学错题学习库', "
                "'table_pages', 'table_questions', 'record_page', 'record_question', NULL, "
                "'2026-07-16 08:05:00', '2026-07-16 08:05:02', "
                "'2026-07-16 08:05:02')"
            )
        )
        counts_before = {
            table: connection.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            for table in (
                "source_assets",
                "problem_regions",
                "ocr_runs",
                "problem_revisions",
                "reviewed_problems",
                "review_status_events",
                "problem_publications",
            )
        }
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    table_names = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        counts_after = {
            table: connection.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            for table in (
                "source_assets",
                "problem_regions",
                "ocr_runs",
                "problem_revisions",
                "problem_assets",
                "problem_publications",
            )
        }
        problem = connection.execute(
            text(
                "SELECT id, problem_region_id, current_revision_id, created_at, updated_at "
                "FROM problem_assets WHERE id = 'problem_preserved'"
            )
        ).one()
        publication = connection.execute(
            text(
                "SELECT id, problem_id, source_asset_id, published_revision_id, "
                "pages_table_id, questions_table_id, page_record_id, question_record_id "
                "FROM problem_publications WHERE id = 'publication_preserved'"
            )
        ).one()
    engine.dispose()

    assert counts_before == {
        "source_assets": 1,
        "problem_regions": 1,
        "ocr_runs": 1,
        "problem_revisions": 1,
        "reviewed_problems": 1,
        "review_status_events": 1,
        "problem_publications": 1,
    }
    assert counts_after == {
        "source_assets": 1,
        "problem_regions": 1,
        "ocr_runs": 1,
        "problem_revisions": 1,
        "problem_assets": 1,
        "problem_publications": 1,
    }
    assert "reviewed_problems" not in table_names
    assert "review_status_events" not in table_names
    assert problem[:3] == ("problem_preserved", "region_preserved", "revision_preserved")
    assert publication == (
        "publication_preserved",
        "problem_preserved",
        "asset_preserved",
        "revision_preserved",
        "table_pages",
        "table_questions",
        "record_page",
        "record_question",
    )
    get_settings.cache_clear()
