from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mistake_notebook_api.api.schemas import ErrorBody, ErrorEnvelope
from mistake_notebook_api.domain.errors import ERROR_STATUS_CODES, AppError

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "req_unknown")


def _response(
    error: AppError,
    request: Request,
    *,
    status_code: int | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=error.code,
            message=error.message,
            details=error.details,
            request_id=_request_id(request),
            retryable=error.retryable,
        )
    )
    return JSONResponse(
        status_code=status_code or ERROR_STATUS_CODES.get(error.code, 500),
        content=envelope.model_dump(mode="json", by_alias=True),
        headers=headers,
    )


async def app_error_handler(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, AppError):
        return await unhandled_error_handler(request, exception)
    error = exception
    return _response(error, request)


async def validation_error_handler(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, RequestValidationError):
        return await unhandled_error_handler(request, exception)
    return _response(AppError("validation_error", "请求内容不符合要求，请检查后重试。"), request)


async def http_error_handler(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, StarletteHTTPException):
        return await unhandled_error_handler(request, exception)
    if exception.status_code == 404:
        error = AppError("route_not_found", "找不到这个接口或资源。")
    elif exception.status_code == 405:
        error = AppError("method_not_allowed", "这个接口不支持当前请求方法。")
    elif exception.status_code == 400:
        error = AppError("bad_request", "请求格式不正确，请检查后重试。")
    else:
        error = AppError(
            "http_error",
            "请求无法完成，请检查后重试。",
            retryable=exception.status_code >= 500,
        )
    return _response(
        error,
        request,
        status_code=exception.status_code,
        headers=exception.headers,
    )


async def unhandled_error_handler(request: Request, exception: Exception) -> JSONResponse:
    # Exception messages and tracebacks may include SQL parameters, OCR text, or
    # filesystem paths. Keep the correlation ID and exception class, but never
    # serialize the exception itself into privacy-sensitive application logs.
    logger.error(
        "unhandled_request_error request_id=%s exception_type=%s",
        _request_id(request),
        type(exception).__name__,
    )
    return _response(AppError("internal_error", "操作失败，请稍后重试。", True), request)
