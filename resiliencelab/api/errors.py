"""Global exception boundary and error handling for the API."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from resiliencelab.api.schemas import ErrorCode, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    """Install global exception handlers on the FastAPI app."""

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _get_request_id(request)
        logger.exception(
            "Unhandled exception [request_id=%s] %s %s",
            request_id,
            request.method,
            request.url.path,
        )
        error = ErrorDetail(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            details={},
        )
        body = ErrorResponse(error=error, request_id=request_id)
        return JSONResponse(status_code=500, content=body.model_dump())

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        request_id = _get_request_id(request)
        error = ErrorDetail(
            code=ErrorCode.INVALID_REQUEST,
            message=str(exc),
            details={},
        )
        body = ErrorResponse(error=error, request_id=request_id)
        return JSONResponse(status_code=400, content=body.model_dump())


def _get_request_id(request: Request) -> str:
    """Extract or generate a request correlation ID."""
    rid = request.headers.get("X-Request-ID", "")
    if rid:
        return rid
    # Check if middleware set it on state
    rid = getattr(request.state, "request_id", "")
    if rid:
        return rid
    return uuid.uuid4().hex[:16]


def new_request_id() -> str:
    """Generate a new request correlation ID."""
    return uuid.uuid4().hex[:16]
