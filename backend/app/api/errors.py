"""Uniform error bodies: `{"detail": {"code", "message"}}` (ADR 0003).

`code` is a stable id the frontend maps to localized text; `message` is English, for
curl users, logs, and as the UI fallback when a code has no translation.
"""

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def api_error(
    status_code: int, code: str, message: str, *, headers: dict[str, str] | None = None
) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message}, headers=headers)


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail: Any = exc.detail
    if not (isinstance(detail, dict) and "code" in detail):
        # Raised by the framework itself (unknown route, wrong method, ...).
        detail = {"code": f"http_{exc.status_code}", "message": str(detail)}
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)


async def _validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    detail = {
        "code": "validation_error",
        "message": "request validation failed",
        # FastAPI's default per-field list, so forms can highlight the offending field.
        "errors": jsonable_encoder(exc.errors()),
    }
    return JSONResponse({"detail": detail}, status_code=422)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
