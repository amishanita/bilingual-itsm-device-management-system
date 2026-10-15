"""Error contract and global exception handlers.

Every error response has the same shape:
    {"detail": {"code": "ERROR_CODE", "message": "English fallback"}}
The frontend translates by code. Stack traces, SQL errors, and request input
are never included in a response.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Fallback codes for errors raised by the framework itself (unknown route, wrong method).
HTTP_STATUS_CODES = {
    400: ("BAD_REQUEST", "The request is not valid."),
    401: ("NOT_AUTHENTICATED", "Authentication is required."),
    403: ("FORBIDDEN", "You do not have permission to do this."),
    404: ("NOT_FOUND", "The requested resource was not found."),
    405: ("METHOD_NOT_ALLOWED", "This method is not allowed for this resource."),
}


class AppError(Exception):
    """An expected error with a stable code for the frontend.

    Raise this from routers, dependencies, and services instead of HTTPException
    so every error follows the same contract.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers
        # Extra keys added to "detail" next to code and message, for example
        # the row-level errors of a CSV import. Never internal exception data.
        self.extra = extra or {}


def error_body(code: str, message: str) -> dict[str, dict[str, object]]:
    """Build the standard error body."""
    return {"detail": {"code": code, "message": message}}


async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    """Return an AppError in the standard format."""
    content = error_body(exc.code, exc.message)
    content["detail"].update(exc.extra)
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


async def handle_http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Convert framework HTTP errors (404, 405, ...) to the standard format."""
    code, message = HTTP_STATUS_CODES.get(exc.status_code, ("HTTP_ERROR", "The request failed."))
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, message),
        headers=exc.headers,
    )


async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return 422 with the failing field locations.

    Only the location and error type are returned. Pydantic also reports the
    submitted value, which could be a password, so it is deliberately dropped.
    """
    fields = [
        {"field": ".".join(str(part) for part in error["loc"]), "type": error["type"]}
        for error in exc.errors()
    ]
    content = {
        "detail": {
            "code": "VALIDATION_ERROR",
            "message": "The request data is not valid.",
            "fields": fields,
        }
    }
    return JSONResponse(status_code=422, content=content)


async def handle_rate_limit(_request: Request, _exc: RateLimitExceeded) -> JSONResponse:
    """Return 429 when a slowapi limit is exceeded."""
    return JSONResponse(
        status_code=429,
        content=error_body("RATE_LIMITED", "Too many requests. Please try again later."),
    )


async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    """Log any unhandled exception and return a generic 500 without details."""
    logger.error("Unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=error_body("INTERNAL_ERROR", "An unexpected error occurred."),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach all handlers to the application."""
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(RateLimitExceeded, handle_rate_limit)
    app.add_exception_handler(Exception, handle_unexpected_error)
