"""Stable error contract: {"error": {"code", "message", "details?}}.

Machine codes are part of the public API — keep them stable.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Stable machine codes -> default HTTP status
ERROR_STATUS: dict[str, int] = {
    "unauthorized": 401,
    "forbidden": 403,
    "validation_error": 422,
    "unknown_printer": 404,
    "not_found": 404,
    "unsupported_for_printer": 409,
    "idempotency_conflict": 409,
    "conflict": 409,
    "rate_limited": 429,
    "queue_full": 429,
    "quota_exceeded": 429,
    "render_error": 500,
    "printer_unreachable": 502,
    "internal_error": 500,
}


class ApiError(Exception):
    """Raise anywhere to produce the canonical error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        details: Any | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status = status or ERROR_STATUS.get(code, 400)
        self.details = details
        super().__init__(message)


def _envelope(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content=_envelope(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope("validation_error", "Request validation failed", exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 429: "rate_limited"}.get(
            exc.status_code, "internal_error" if exc.status_code >= 500 else "validation_error"
        )
        return JSONResponse(
            status_code=exc.status_code, content=_envelope(code, str(exc.detail))
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500, content=_envelope("internal_error", "Internal server error")
        )
