"""Exception handlers that answer with application/problem+json (RFC 9457)."""

import json
import logging
from typing import Any

from app.shared.base_error import BaseError
from app.shared.ids import new_id

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PROBLEM_JSON = "application/problem+json"

log = structlog.get_logger(__name__)


def problem_response(status: int, body: dict[str, Any]) -> JSONResponse:
    """Build a problem+json response."""
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def _title(request: Request, key: str, params: dict[str, Any]) -> str:
    """English message for the problem title; falls back to the message key."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return key
    title: str = container.i18n.t("en", key, **params)
    return title


def _internal_body(error_id: str) -> dict[str, Any]:
    return {
        "type": "common/internal",
        "title": "Internal Server Error",
        "status": 500,
        "message_key": "error-internal",
        "params": {},
        "error_id": error_id,
    }


def problem_body(request: Request, exc: BaseError) -> dict[str, Any]:
    """The problem+json body of a domain error (no `error_id`, no logging)."""
    return {
        "type": exc.code,
        "title": _title(request, exc.message_key, exc.params),
        "status": exc.status,
        "message_key": exc.message_key,
        "params": exc.params,
    }


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers for domain errors, HTTP errors, validation and crashes."""

    @app.exception_handler(BaseError)
    async def handle_base_error(request: Request, exc: BaseError) -> JSONResponse:
        """Map a BaseError to its status and stable type."""
        body = problem_body(request, exc)
        if exc.status >= 500:
            error_id = str(new_id())
            body["error_id"] = error_id
            log.error(
                "domain_error",
                error_id=error_id,
                code=exc.code,
                support_details=exc.support_details,
                path=request.url.path,
            )
        else:
            log.info(
                "domain_error",
                code=exc.code,
                support_details=exc.support_details,
                path=request.url.path,
            )
        return problem_response(exc.status, body)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Router-level 404/405 and other HTTP exceptions."""
        body = {
            "type": "about:blank",
            "title": str(exc.detail),
            "status": exc.status_code,
        }
        response = problem_response(exc.status_code, body)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Request body, query or path does not match the schema."""
        # Whitelist keys: errors() holds `input` (may contain secrets).
        errors = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        body = {
            "type": "common/request-validation",
            "title": "Request validation failed",
            "status": 422,
            "message_key": "error-validation",
            "params": {},
            "errors": errors,
        }
        return problem_response(422, body)

    @app.exception_handler(Exception)
    async def handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Last resort when CatchAllMiddleware did not see the crash."""
        error_id = str(new_id())
        log.error(
            "unhandled_exception",
            error_id=error_id,
            path=request.url.path,
            exc_info=exc,
        )
        return problem_response(500, _internal_body(error_id))


class CatchAllMiddleware:
    """Turn a crash into problem+json inside the CORS layer, so the 500 has CORS."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the next ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run the app; answer 500 problem+json if it crashes before responding."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # noqa: BLE001 - last line of defence, logged below
            error_id = str(new_id())
            logging.getLogger(__name__).exception(
                "unhandled_exception error_id=%s path=%s", error_id, scope.get("path")
            )
            if started:
                raise
            del exc
            body = json.dumps(_internal_body(error_id)).encode()
            headers = [
                (b"content-type", PROBLEM_JSON.encode()),
                (b"content-length", str(len(body)).encode()),
            ]
            await send(
                {"type": "http.response.start", "status": 500, "headers": headers}
            )
            await send({"type": "http.response.body", "body": body})
