"""Per-route-group CORS as a path-prefix ASGI middleware.

Rules: the cookie endpoints (`/v1/oauth/token|refresh|logout`) allow the first-party
app origins with credentials and require the `X-IHSP-Client` header; the public share
data (`/v1/public/*`) allows only the share host; every other `/v1/*` route allows the
first-party app origins without credentials. The share host shows user-written content
and is never a credentialed origin.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.settings import Settings
from app.shared.base_error import ForbiddenError

from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from app.bootstrap.container import Container

CLIENT_HEADER = "x-ihsp-client"

COOKIE_PREFIXES = ("/v1/oauth/token", "/v1/oauth/refresh", "/v1/oauth/logout")
PUBLIC_PREFIXES = ("/v1/public/",)
APP_PREFIXES = ("/v1/",)

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_EXPOSE = ["X-Request-ID", "Retry-After", "Content-Disposition"]
# Credentials forbid a wildcard, so the cookie group lists its headers.
_COOKIE_HEADERS = [
    "Content-Type",
    "X-IHSP-Client",
    "X-Request-ID",
    "Accept-Language",
]


def _matches(path: str, prefix: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


class PrefixCorsMiddleware:
    """Pick the CORS policy by path prefix; paths outside every group get none."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        app_origins: Sequence[str],
        share_origins: Sequence[str],
    ) -> None:
        """Build one CORSMiddleware per route group."""
        self.app = app
        self.groups: list[tuple[tuple[str, ...], CORSMiddleware]] = [
            (
                COOKIE_PREFIXES,
                CORSMiddleware(
                    app,
                    allow_origins=list(app_origins),
                    allow_credentials=True,
                    allow_methods=["POST", "OPTIONS"],
                    allow_headers=_COOKIE_HEADERS,
                    expose_headers=_EXPOSE,
                ),
            ),
            (
                PUBLIC_PREFIXES,
                CORSMiddleware(
                    app,
                    allow_origins=list(share_origins),
                    allow_credentials=False,
                    allow_methods=_METHODS,
                    allow_headers=["*"],
                    expose_headers=_EXPOSE,
                ),
            ),
            (
                APP_PREFIXES,
                CORSMiddleware(
                    app,
                    allow_origins=list(app_origins),
                    allow_credentials=False,
                    allow_methods=_METHODS,
                    allow_headers=["*"],
                    expose_headers=_EXPOSE,
                ),
            ),
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Delegate to the first group whose prefix matches the path."""
        if scope["type"] == "http":
            path: str = scope["path"]
            for prefixes, cors in self.groups:
                if any(_matches(path, prefix) for prefix in prefixes):
                    await cors(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def apply_cors(app: FastAPI, settings: Settings) -> None:
    """Install the per-prefix CORS middleware (outermost user middleware)."""
    app.add_middleware(
        PrefixCorsMiddleware,
        app_origins=settings.cors_app_origins(),
        share_origins=settings.cors_share_origins(),
    )


def require_client_header(request: Request) -> None:
    """Cookie endpoints: need X-IHSP-Client and an Origin of one of our apps."""
    container: Container = request.app.state.container
    origin = request.headers.get("origin")
    if not request.headers.get(CLIENT_HEADER) or origin not in (
        container.settings.cors_app_origins()
    ):
        raise ForbiddenError(support_details="missing X-IHSP-Client or bad Origin")
