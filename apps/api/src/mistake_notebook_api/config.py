from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPOSITORY_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = f"sqlite:///{(REPOSITORY_ROOT / 'data' / 'mistake-notebook.db').as_posix()}"
    storage_root: Path = REPOSITORY_ROOT / "storage"
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, gt=0)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
    min_region_pixels: int = Field(default=4, gt=0)
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    ocr_provider: str = "paddleocr_vl_api"
    ocr_timeout_seconds: int = Field(default=120, gt=0)
    paddleocr_language: str = "ch"
    paddleocr_model_name: str = "PP-OCRv5_server_rec"
    paddleocr_access_token: SecretStr | None = None
    paddleocr_api_job_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddleocr_vl_model: str = "PaddleOCR-VL-1.6"
    paddleocr_api_request_timeout_seconds: int = Field(default=30, gt=0)
    paddleocr_api_poll_interval_seconds: float = Field(default=5, gt=0)

    region_detection_provider: str = "manual"
    yescan_api_key_id: str | None = None
    yescan_api_key: SecretStr | None = None
    yescan_api_base_url: str = "https://scan-business.quark.cn/vision"
    yescan_timeout_seconds: int = Field(default=120, gt=0)

    problem_publisher: str = "lark_cli"
    lark_base_title: str = "小学数学错题学习库"
    lark_cli_command: str = "lark-cli"
    lark_publish_timeout_seconds: int = Field(default=120, gt=0)

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
