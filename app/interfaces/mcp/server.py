"""Entry points of the MCP interface: the five servers and their root routes.

I1 mounts every `(path, app)` pair on the API app, enters every lifespan context in
the app's lifespan (the SDK session managers must run there; a mounted sub-app's own
lifespan never runs) and adds `protected_resource_routes(settings)` to the app.
"""

from collections.abc import Awaitable, Callable, Collection
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.interfaces.mcp.admin.server import build_admin_server
from app.interfaces.mcp.constants import MOUNT_PREFIX, SCOPES_BY_SERVER, SERVERS
from app.interfaces.mcp.deps import McpDeps, deps_from_container
from app.interfaces.mcp.endpoints import resource_url
from app.interfaces.mcp.lms.server import build_lms_server
from app.interfaces.mcp.ports import ConnectorCoursesPort, McpAuditPort
from app.interfaces.mcp.student.server import build_student_server
from app.interfaces.mcp.teacher.server import build_teacher_server
from app.interfaces.mcp.universal.server import build_app_server
from app.settings import Settings
from app.shared.brand import current_brand
from app.shared.contracts.ai import AdminToolBackend

from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.routes import (
    cors_middleware,
    create_protected_resource_routes,
)
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import ProtectedResourceMetadata
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.types import ASGIApp

if TYPE_CHECKING:
    from app.bootstrap.container import Container

McpApp = tuple[str, ASGIApp, AbstractAsyncContextManager[None]]

PublishedKinds = Callable[[], Awaitable[Collection[str]]]
"""The kinds of legal documents that have a published version right now."""

# Kinds that the resource metadata advertises (RFC 9728 `resource_tos_uri` and
# `resource_policy_uri`); the pages live in the id app at `/legal/<kind>/`.
TERMS_KIND = "terms"
PRIVACY_KIND = "privacy"

_BUILDERS: dict[str, Callable[[McpDeps], FastMCP]] = {
    "student": build_student_server,
    "lms": build_lms_server,
    "admin": build_admin_server,
    "teacher": build_teacher_server,
    "app": build_app_server,
}


def build_mcp_apps(
    container: "Container",
    *,
    audit: McpAuditPort | None = None,
    admin_tools: AdminToolBackend | None = None,
    connector_courses: ConnectorCoursesPort | None = None,
) -> list[McpApp]:
    """Build the five servers: `("/mcp/student", app, lifespan_cm)` and so on.

    Call once per process: each lifespan context manager can be entered only once.
    """
    deps = deps_from_container(
        container,
        audit=audit,
        admin_tools=admin_tools,
        connector_courses=connector_courses,
    )
    return build_apps(deps)


def build_apps(deps: McpDeps) -> list[McpApp]:
    """Build the servers from collected dependencies (used by tests)."""
    apps: list[McpApp] = []
    for name in SERVERS:
        server = _BUILDERS[name](deps)
        app = server.streamable_http_app()  # creates server.session_manager
        apps.append((f"{MOUNT_PREFIX}/{name}", app, server.session_manager.run()))
    return apps


def legal_uri(settings: Settings, kind: str) -> AnyHttpUrl:
    """Public page of a legal document, as the web app links it."""
    return AnyHttpUrl(f"{settings.urls.id.rstrip('/')}/legal/{kind}/")


def _legal_metadata_route(
    route: Route,
    metadata: ProtectedResourceMetadata,
    settings: Settings,
    published: PublishedKinds,
) -> Route:
    """The SDK's metadata route, with legal URLs of the documents published now."""

    async def handle(request: Request) -> Response:
        kinds = await published()
        body = metadata.model_copy(
            update={
                "resource_tos_uri": (
                    legal_uri(settings, TERMS_KIND) if TERMS_KIND in kinds else None
                ),
                "resource_policy_uri": (
                    legal_uri(settings, PRIVACY_KIND) if PRIVACY_KIND in kinds else None
                ),
            }
        )
        return PydanticJSONResponse(
            content=body, headers={"Cache-Control": "public, max-age=300"}
        )

    return Route(
        route.path,
        endpoint=cors_middleware(handle, ["GET", "OPTIONS"]),
        methods=["GET", "OPTIONS"],
    )


def protected_resource_routes(
    settings: Settings, published: PublishedKinds | None = None
) -> list[Route]:
    """RFC 9728 metadata routes for the host root, one per server.

    The SDK registers them inside each mounted sub-app, where the `resource_metadata`
    URL of a 401 does not point. The path advertised by the 401 is served here; when
    it does not already start with `/mcp` the same metadata is also served under
    `/mcp`, for a proxy that maps the host `mcp.ihsu.uz` to the app's `/mcp/` prefix.
    With `published` the metadata also carries the terms and privacy URLs of the legal
    documents managed in Administration, for the kinds that have a published version.
    """
    routes: list[Route] = []
    issuer = AnyHttpUrl(settings.hydra.issuer)
    for server in SERVERS:
        url = AnyHttpUrl(resource_url(settings, server))
        created = create_protected_resource_routes(
            resource_url=url,
            authorization_servers=[issuer],
            # offline_access: clients ask for what is listed; without it no refresh
            # token, and a 15 minute access token means signing in again.
            scopes_supported=[*SCOPES_BY_SERVER[server], "offline_access"],
            resource_name=f"{current_brand().name} {server}",
        )
        if published is not None:
            metadata = ProtectedResourceMetadata(
                resource=url,
                authorization_servers=[issuer],
                scopes_supported=[*SCOPES_BY_SERVER[server], "offline_access"],
                resource_name=f"{current_brand().name} {server}",
            )
            created = [
                _legal_metadata_route(r, metadata, settings, published) for r in created
            ]
        routes.extend(created)
        routes.extend(_prefixed(created, url))
    return routes


def _prefixed(routes: list[Route], url: AnyHttpUrl) -> list[Route]:
    """Copies of the metadata routes under /mcp, unless they are already there."""
    if urlparse(str(url)).path.startswith(f"{MOUNT_PREFIX}/"):
        return []
    return [
        Route(
            f"{MOUNT_PREFIX}{route.path}",
            endpoint=route.endpoint,
            methods=sorted(route.methods or ()),
        )
        for route in routes
    ]
