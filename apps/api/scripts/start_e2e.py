from __future__ import annotations

import sys
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT / "src"))


def main() -> None:
    alembic_config = Config(str(API_ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    uvicorn.run(
        "mistake_notebook_api.main:app",
        app_dir=str(API_ROOT / "src"),
        host="127.0.0.1",
        port=8001,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
