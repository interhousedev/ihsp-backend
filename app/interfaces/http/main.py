"""FastAPI application factory shared by every HTTP process."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import cast

from app.bootstrap.container import Container
from app.interfaces.http.cors import apply_cors
from app.interfaces.http.errors import CatchAllMiddleware, install_error_handlers

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp

READY_TIMEOUT_SECONDS = 3


async def _check_db(container: Container) -> bool:
    try:
        async with asyncio.timeout(READY_TIMEOUT_SECONDS):
            async with container.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        return False
    return True


async def _check_redis(container: Container) -> bool:
    try:
        async with asyncio.timeout(READY_TIMEOUT_SECONDS):
            await cast(Awaitable[bool], container.redis.ping())
    except (RedisError, OSError):
        return False
    return True


def create_app(
    container: Container,
    *,
    routers: Sequence[APIRouter],
    mounts: Sequence[tuple[str, ASGIApp]] = (),
    lifespan_hooks: Sequence[Callable[[], AbstractAsyncContextManager[None]]] = (),
) -> FastAPI:
    """Build the app: error handlers, CORS, health endpoints, routers and mounts."""
    settings = container.settings
    production = settings.env == "prod"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for hook in lifespan_hooks:
                await stack.enter_async_context(hook())
            yield

    app = FastAPI(
        title=settings.public_app_name,
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
        telemetry={"tracing": False, "metrics": False, "logs": False},
    )
    app.state.container = container
    install_error_handlers(app)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        """Readiness probe: PostgreSQL and Redis answer."""
        checks = {
            "db": await _check_db(container),
            "redis": await _check_redis(container),
        }
        ok = all(checks.values())
        body = {"status": "ok" if ok else "unavailable", "checks": checks}
        return JSONResponse(body, status_code=200 if ok else 503)

    for router in routers:
        app.include_router(router)
    for path, asgi_app in mounts:
        app.mount(path, asgi_app)

    # Added first = innermost: a crash becomes problem+json before CORS runs.
    app.add_middleware(CatchAllMiddleware)
    apply_cors(app, settings)
    return app
