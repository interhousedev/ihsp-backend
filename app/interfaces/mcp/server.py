"""Entry points of the MCP interface: the three servers and their root routes.

I1 mounts every `(path, app)` pair on the API app, enters every lifespan context in
the app's lifespan (the SDK session managers must run there; a mounted sub-app's own
lifespan never runs) and adds `protected_resource_routes(settings)` to the app.
"""

from collections.abc import Callable
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
from app.settings import Settings
from app.shared.contracts.ai import AdminToolBackend

from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.routing import Route
from starlette.types import ASGIApp

if TYPE_CHECKING:
    from app.bootstrap.container import Container

McpApp = tuple[str, ASGIApp, AbstractAsyncContextManager[None]]

_BUILDERS: dict[str, Callable[[McpDeps], FastMCP]] = {
    "student": build_student_server,
    "lms": build_lms_server,
    "admin": build_admin_server,
}


def build_mcp_apps(
    container: "Container",
    *,
    audit: McpAuditPort | None = None,
    admin_tools: AdminToolBackend | None = None,
    connector_courses: ConnectorCoursesPort | None = None,
) -> list[McpApp]:
    """Build the three servers: `("/mcp/student", app, lifespan_cm)` and so on.

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


def protected_resource_routes(settings: Settings) -> list[Route]:
    """RFC 9728 metadata routes for the host root, one per server.

    The SDK registers them inside each mounted sub-app, where the `resource_metadata`
    URL of a 401 does not point. The path advertised by the 401 is served here; when
    it does not already start with `/mcp` the same metadata is also served under
    `/mcp`, for a proxy that maps the host `mcp.ihsu.uz` to the app's `/mcp/` prefix.
    """
    routes: list[Route] = []
    issuer = AnyHttpUrl(settings.hydra.issuer)
    for server in SERVERS:
        url = AnyHttpUrl(resource_url(settings, server))
        created = create_protected_resource_routes(
            resource_url=url,
            authorization_servers=[issuer],
            scopes_supported=list(SCOPES_BY_SERVER[server]),
            resource_name=f"IHT {server}",
        )
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
