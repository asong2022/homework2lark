from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from mistake_notebook_api.api.errors import (
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from mistake_notebook_api.api.middleware import RequestContextMiddleware
from mistake_notebook_api.api.routes import router
from mistake_notebook_api.api.runtime import Runtime, build_runtime
from mistake_notebook_api.config import Settings, get_settings
from mistake_notebook_api.domain.errors import AppError


def create_app(*, settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    application = FastAPI(
        title="小学数学错题学习系统 API",
        version="0.1.0",
        description=(
            "这是提供给 AI 与开发者的配置接口，不是教师日常操作页面。"
            "当前支持：上传单页图片、教师框题、OCR、人工修订、来源追溯和发布飞书 Base。"
        ),
        openapi_tags=[
            {"name": "来源图片", "description": "保存和读取不可覆盖的原始作业图片。"},
            {"name": "题目录入", "description": "保存教师确认的题目区域与裁图。"},
            {"name": "OCR 与修订", "description": "保留机器识别证据并追加教师修订版本。"},
            {"name": "飞书 Base", "description": "显式发布教师确认修订后的题目资产。"},
            {"name": "系统状态", "description": "供 AI 或开发者诊断本地服务。"},
        ],
    )
    application.state.runtime = runtime or build_runtime(settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    # Starlette applies the most recently registered middleware outermost.
    # Keep request correlation outside CORS so denied preflights are still logged
    # and receive X-Request-ID even though CORSMiddleware owns their plain-text body.
    application.add_middleware(RequestContextMiddleware)
    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)
    application.include_router(router)
    return application


app = create_app()
