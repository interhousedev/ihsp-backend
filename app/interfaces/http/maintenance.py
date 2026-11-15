"""Maintenance mode for the HTTP edge: writes get 503 problem+json, reads pass."""

from collections.abc import Callable

from app.interfaces.http.errors import problem_body, problem_response
from app.shared.maintenance import MaintenanceError, MaintenanceGate

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

_WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Sign-in and the migration page itself must work, or the admin could not roll back.
# MCP reads are POSTs too; its guard refuses the writing tools itself.
_EXEMPT_PREFIXES = ("/v1/id/", "/oauth/", "/v1/admin/migration", "/mcp/")
_EXEMPT_PATHS = frozenset({"/health", "/ready"})
RETRY_AFTER_SECONDS = "60"


class MaintenanceMiddleware:
    """Refuse every write while the platform is being moved to another server."""

    def __init__(self, app: ASGIApp, gate: Callable[[], MaintenanceGate]) -> None:
        """Wrap the next ASGI app; `gate` returns the service that knows the state."""
        self.app = app
        self.gate = gate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer 503 to a write in maintenance mode; pass everything else on."""
        if scope["type"] != "http" or scope["method"] not in _WRITES:
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        if path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return
        if not self.gate().info().active:
            await self.app(scope, receive, send)
            return
        body = problem_body(Request(scope), MaintenanceError())
        response = problem_response(503, body)
        response.headers["Retry-After"] = RETRY_AFTER_SECONDS
        await response(scope, receive, send)
