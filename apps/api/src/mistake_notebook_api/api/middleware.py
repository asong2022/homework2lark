from __future__ import annotations

import logging
from time import perf_counter

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from mistake_notebook_api.domain.identifiers import new_id

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or new_id("req")
        request.state.request_id = request_id
        started = perf_counter()
        response = await call_next(request)
        elapsed_ms = round((perf_counter() - started) * 1000)
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        logger.info(
            "request_completed request_id=%s method=%s route=%s status_code=%s elapsed_ms=%s",
            request_id,
            request.method,
            route_path,
            response.status_code,
            elapsed_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
