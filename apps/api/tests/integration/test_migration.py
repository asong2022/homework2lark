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
    "reviewed_problems",
    "review_status_events",
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
