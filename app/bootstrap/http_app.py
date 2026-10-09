"""The FastAPI application of an HTTP process (all, identity, api)."""

import asyncio
import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from app.bootstrap.common import build_container
from app.bootstrap.container import Container
from app.interfaces.http.main import create_app
from app.interfaces.http.routing import (
    install_mcp_host,
    install_short_link_host,
    routers_for,
)
from app.settings import Settings
from app.shared.logging import configure_logging

import structlog
import uvicorn
from fastapi import FastAPI
from starlette.types import ASGIApp

log = structlog.get_logger(__name__)

PORTS = {"all": 8000, "api": 8000, "identity": 8001}
HOSTS_WITH_MCP = ("all", "api")


def _hook(
    manager: AbstractAsyncContextManager[None],
) -> Callable[[], AbstractAsyncContextManager[None]]:
    """A lifespan hook that enters an already created session manager."""

    def enter() -> AbstractAsyncContextManager[None]:
        return manager

    return enter


def mcp_parts(
    container: Container,
) -> tuple[
    list[tuple[str, ASGIApp]],
    list[Callable[[], AbstractAsyncContextManager[None]]],
]:
    """Mounts and lifespan hooks of the three MCP servers (built once per process)."""
    from app.interfaces.mcp.server import build_mcp_apps

    apps = build_mcp_apps(container)
    mounts = [(path, asgi_app) for path, asgi_app, _ in apps]
    hooks = [_hook(manager) for _, _, manager in apps]
    return mounts, hooks


def build_http_app(container: Container, *, process: str) -> FastAPI:
    """Create the app of one HTTP process: routers, MCP, host routing.

    `all` serves every router of `identity` and `api`; `identity` and `api` serve
    their own groups. MCP servers (`/mcp/<server>`) and their metadata routes belong
    to `all` and `api`.
    """
    mounts: list[tuple[str, ASGIApp]] = []
    hooks: list[Callable[[], AbstractAsyncContextManager[None]]] = []
    if process in HOSTS_WITH_MCP:
        mounts, hooks = mcp_parts(container)
    app = create_app(
        container,
        routers=routers_for(process, container.settings),
        mounts=mounts,
        lifespan_hooks=hooks,
    )
    if process in HOSTS_WITH_MCP:
        from app.interfaces.mcp.server import protected_resource_routes

        metadata = protected_resource_routes(container.settings)
        app.router.routes.extend(metadata)
        install_short_link_host(app, container)
        install_mcp_host(app, container, mounts, metadata)
    install_extras(app, container, process)
    return app


def install_extras(app: FastAPI, container: Container, process: str) -> None:
    """Hook for pieces added by other tasks (composition endpoints)."""
    if process not in HOSTS_WITH_MCP:
        return
    try:
        from app.bootstrap.composition import install_composition_for
    except ImportError:
        log.warning("composition_not_available")
        return
    install_composition_for(app, container)


async def serve(settings: Settings, *, process: str) -> None:
    """Build the container and the app, then run Uvicorn until interrupted."""
    from app.interfaces.jobs.broker import broker

    await broker.startup()
    container = await build_container(settings, process=process)
    app = build_http_app(container, process=process)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",  # noqa: S104 - the container network is the boundary
        port=int(os.environ.get("PORT", PORTS[process])),
        log_config=None,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )
    try:
        await uvicorn.Server(config).serve()
    finally:
        await container.close()
        await broker.shutdown()


def run_http(settings: Settings, process: str) -> int:
    """Entry point of `python -m app all|identity|api`."""
    configure_logging(settings.log_level, json_logs=settings.env == "prod")
    asyncio.run(serve(settings, process=process))
    return 0
