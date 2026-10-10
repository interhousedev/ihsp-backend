"""Which routers each HTTP process serves, and host routing for short links."""

import importlib
from collections.abc import Sequence
from urllib.parse import urlparse

from app.bootstrap.container import Container
from app.interfaces.http.main import create_app
from app.settings import Settings
from app.shared.features import Feature

import structlog
from fastapi import APIRouter, FastAPI
from starlette.routing import BaseRoute, Host, Mount, Router
from starlette.types import ASGIApp

log = structlog.get_logger(__name__)

V1 = "app.interfaces.http.v1"
PUBLIC = "app.interfaces.http.public"

# `/v1/id/*`, `/v1/oauth/*`, `/v1/admin/{users,teachers,audit}`, `/internal/emis/*`.
IDENTITY_PACKAGES: tuple[str, ...] = (
    f"{V1}.id",
    f"{V1}.id_registration",
    f"{V1}.oauth",
    f"{V1}.admin_users",
    "app.interfaces.http.internal.emis",
)

# Everything else under `/v1/*` plus the public pages (served by the `api` process).
API_PACKAGES: tuple[str, ...] = (
    # Composition first: `/v1/admin/groups/stats` must win over `/v1/admin/groups/{id}`.
    f"{V1}.composition",
    f"{V1}.me_schedule",
    f"{V1}.me_teachers",
    f"{V1}.me_photo",
    f"{V1}.dashboard",
    f"{V1}.me_classwork",
    f"{V1}.me_marks",
    f"{V1}.me_curriculum",
    f"{V1}.me_assessments",
    f"{V1}.staff_assessments",
    f"{V1}.admin_assessments",
    f"{V1}.staff_classwork",
    f"{V1}.staff_groups",
    f"{V1}.admin_schedule",
    f"{V1}.admin_attendance",
    f"{V1}.admin_sync",
    f"{V1}.admin_insights",
    f"{V1}.admin_broadcasts",
    f"{V1}.admin_settings",
    f"{V1}.admin_moderation",
    f"{V1}.files",
    f"{V1}.links",
    f"{V1}.notifications",
    f"{V1}.push",
    f"{V1}.app_version",
    f"{V1}.ai",
    f"{V1}.web_search",
    f"{V1}.outbound_mail",
    f"{V1}.flashcards",
    f"{V1}.notebooks",
    f"{V1}.library",
    f"{V1}.lms_authoring",
    f"{V1}.lms_learning",
    f"{PUBLIC}.rooms",
    f"{PUBLIC}.short_links",
    f"{PUBLIC}.library",
    f"{PUBLIC}.robots",
    f"{PUBLIC}.ical",
)

SHORT_LINKS_PACKAGE = f"{PUBLIC}.short_links"

# A router package that belongs to a feature is left out while `FEATURES__<NAME>` is
# off, so its URLs answer 404.
FEATURE_PACKAGES: dict[str, Feature] = {
    f"{V1}.ai": Feature.AI_ASSISTANT,
    f"{V1}.flashcards": Feature.FLASHCARDS,
    f"{V1}.notebooks": Feature.NOTEBOOKS,
    f"{V1}.library": Feature.LIBRARY,
    f"{PUBLIC}.library": Feature.LIBRARY,
    f"{V1}.lms_authoring": Feature.LMS,
    f"{V1}.lms_learning": Feature.LMS,
    f"{V1}.push": Feature.PUSH,
    f"{V1}.admin_sync": Feature.EMIS_SYNC,
}


def _import_routers(package: str) -> list[APIRouter]:
    """Return the `ROUTERS` (or the single `router`) of a router package."""
    try:
        module = importlib.import_module(package)
    except ModuleNotFoundError as exc:
        if exc.name is None or not package.startswith(exc.name):
            raise  # a broken import inside the package is a bug, not a missing task
        log.warning("router_package_missing", package=package)
        return []
    routers: list[APIRouter] | None = getattr(module, "ROUTERS", None)
    if routers is not None:
        return list(routers)
    router: APIRouter | None = getattr(module, "router", None)
    return [router] if router is not None else []


def collect_routers(
    packages: tuple[str, ...], settings: Settings | None = None
) -> list[APIRouter]:
    """Routers of the packages, in order; with `settings`, switched-off features go."""
    routers: list[APIRouter] = []
    for package in packages:
        feature = FEATURE_PACKAGES.get(package)
        if (
            settings is not None
            and feature
            and not getattr(settings.features, feature.value)
        ):
            log.info("router_feature_off", package=package, feature=feature.value)
            continue
        routers.extend(_import_routers(package))
    return routers


def routers_for(process: str, settings: Settings | None = None) -> list[APIRouter]:
    """The routers of one HTTP process (`all`, `identity` or `api`).

    Pass `settings` to leave out the routers of features that are switched off.
    """
    if process == "identity":
        return collect_routers(IDENTITY_PACKAGES, settings)
    if process == "api":
        return collect_routers(API_PACKAGES, settings)
    return collect_routers(IDENTITY_PACKAGES + API_PACKAGES, settings)


def _host(url: str) -> str | None:
    return urlparse(url).hostname


def install_short_link_host(app: FastAPI, container: Container) -> None:
    """Serve `s.ihsu.uz/{slug}` by Host: that host maps `/{slug}` to the short link.

    In development the short links live under `/s` of the API host; the host sub-app
    is only added when the short-link host differs from the API host.
    """
    settings = container.settings
    short_host = _host(settings.urls.short_links)
    if not short_host or short_host == _host(settings.urls.api):
        return
    module = importlib.import_module(SHORT_LINKS_PACKAGE)
    host_routers: list[APIRouter] = list(getattr(module, "HOST_ROUTERS", []))
    if not host_routers:
        return
    sub = create_app(container, routers=host_routers)
    app.router.routes.insert(0, Host(short_host, app=sub))


MCP_PREFIX = "/mcp"


def install_mcp_host(
    app: FastAPI,
    container: Container,
    mounts: list[tuple[str, ASGIApp]],
    metadata_routes: Sequence[BaseRoute],
) -> None:
    """Serve the MCP servers at the root of their own host (`mcp.ihsu.uz/student`).

    Used when `URLS__MCP` is a host root that differs from the API host. The same
    ASGI apps stay mounted under `/mcp/<server>` for development; the SDK session
    managers are entered once by the main app's lifespan.
    """
    settings = container.settings
    parsed = urlparse(settings.urls.mcp)
    host = parsed.hostname
    if not host or parsed.path.strip("/") or host == _host(settings.urls.api):
        return
    routes: list[BaseRoute] = list(metadata_routes)
    routes.extend(
        Mount(path.removeprefix(MCP_PREFIX), app=asgi_app)
        for path, asgi_app in mounts
        if path.startswith(f"{MCP_PREFIX}/")
    )
    app.router.routes.insert(0, Host(host, app=Router(routes=routes)))
