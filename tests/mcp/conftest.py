"""Fixtures of the MCP tests: a world of fakes and an in-process HTTP server."""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

from app.interfaces.mcp.constants import SCOPES_BY_SERVER, ServerName
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.ports import McpFilesApi
from app.interfaces.mcp.server import build_apps, protected_resource_routes
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import (
    ClassworkQueries,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.ai import AdminToolBackend
from app.shared.contracts.auth import AccessTokenVerifier, ConnectorTokenVerifier
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import LmsDraftCommands, LmsQueries
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from tests.fakes.clock import FixedClock
from tests.mcp.fakes import (
    FakeAccessVerifier,
    FakeAdminTools,
    FakeClasswork,
    FakeConnectorCourses,
    FakeConnectorVerifier,
    FakeFiles,
    FakeFlashcards,
    FakeLinks,
    FakeLmsCommands,
    FakeLmsQueries,
    FakeMarks,
    FakeSchedule,
    RecordingAudit,
)

import httpx
import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE_URL = "http://testserver"


class RunningServer:
    """The three servers mounted on one app, reachable over an ASGI transport."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.raw = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE_URL
        )

    @contextlib.asynccontextmanager
    async def session(self, server: str, token: str) -> AsyncIterator[ClientSession]:
        """An initialized MCP client session with a bearer token."""
        headers = {"authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=BASE_URL,
            headers=headers,
        ) as client:
            url = f"{BASE_URL}/mcp/{server}/"
            async with streamable_http_client(url, http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session


@dataclass
class World:
    """Fakes, the dependencies built from them and helpers to mint tokens."""

    settings: Settings
    clock: FixedClock
    redis: FakeRedis
    i18n: I18nCore
    access: FakeAccessVerifier = field(default_factory=FakeAccessVerifier)
    connector: FakeConnectorVerifier = field(default_factory=FakeConnectorVerifier)
    audit: RecordingAudit = field(default_factory=RecordingAudit)
    connector_courses: FakeConnectorCourses = field(
        default_factory=FakeConnectorCourses
    )
    schedule: FakeSchedule = field(default_factory=FakeSchedule)
    classwork: FakeClasswork = field(default_factory=FakeClasswork)
    marks: FakeMarks = field(default_factory=FakeMarks)
    files: FakeFiles = field(default_factory=FakeFiles)
    links: FakeLinks = field(default_factory=FakeLinks)
    flashcards: FakeFlashcards = field(default_factory=FakeFlashcards)
    lms_queries: FakeLmsQueries = field(default_factory=FakeLmsQueries)
    lms_commands: FakeLmsCommands = field(default_factory=FakeLmsCommands)
    admin_tools: FakeAdminTools = field(default_factory=FakeAdminTools)

    def deps(self, *, with_course_port: bool = False) -> McpDeps:
        """Collect the fakes into the dependencies of the servers."""
        return McpDeps(
            settings=self.settings,
            clock=self.clock,
            rate_limiter=RateLimiter(self.redis),
            i18n=self.i18n,
            audit=self.audit,
            connector_courses=self.connector_courses if with_course_port else None,
            access_verifier=cast(AccessTokenVerifier, self.access),
            connector_verifier=cast(ConnectorTokenVerifier, self.connector),
            schedule=cast(ScheduleQueries, self.schedule),
            classwork=cast(ClassworkQueries, self.classwork),
            marks=cast(MarksQueries, self.marks),
            files=cast(McpFilesApi, self.files),
            links=cast(LinksApi, self.links),
            flashcards=cast(FlashcardsApi, self.flashcards),
            lms_queries=cast(LmsQueries, self.lms_queries),
            lms_commands=cast(LmsDraftCommands, self.lms_commands),
            admin_tools=cast(AdminToolBackend, self.admin_tools),
        )

    def connector_token(
        self,
        server: ServerName,
        *scopes: str,
        roles: tuple[Role, ...] | None = None,
        user_id: UUID | None = None,
    ) -> tuple[str, Actor]:
        """Register a connector token with these scopes; return (token, actor)."""
        default_roles = {
            "student": (Role.STUDENT,),
            "lms": (Role.TEACHER,),
            "admin": (Role.ADMIN,),
        }[server]
        actor = Actor(
            user_id=user_id or new_id(),
            roles=frozenset(roles if roles is not None else default_roles),
            connector_id=new_id(),
            scopes=frozenset(scopes),
        )
        token = f"ihsp_mcp_{uuid4().hex}"
        self.connector.tokens[token] = (server, actor)
        return token, actor

    def oauth_token(
        self, audience: str, *scopes: str, roles: tuple[Role, ...] = (Role.STUDENT,)
    ) -> tuple[str, Actor]:
        """Register a Hydra access token for an audience; return (token, actor)."""
        actor = Actor(
            user_id=new_id(),
            roles=frozenset(roles),
            client_id="mcp-client",
            scopes=frozenset(scopes),
        )
        token = f"jwt-{uuid4().hex}"
        self.access.tokens[token] = (audience, actor)
        return token, actor

    def all_scopes(self, server: ServerName) -> tuple[str, ...]:
        """Every scope of a server."""
        return SCOPES_BY_SERVER[server]

    @contextlib.asynccontextmanager
    async def serve(
        self, *, with_course_port: bool = False
    ) -> AsyncIterator[RunningServer]:
        """Build fresh servers (session managers are single-use) and run them."""
        apps = build_apps(self.deps(with_course_port=with_course_port))
        async with contextlib.AsyncExitStack() as stack:
            app = FastAPI(lifespan=None)
            app.router.routes.extend(protected_resource_routes(self.settings))
            for path, asgi_app, lifespan in apps:
                app.mount(path, asgi_app)
                await stack.enter_async_context(lifespan)
            server = RunningServer(app)
            try:
                yield server
            finally:
                await server.raw.aclose()

    @contextlib.asynccontextmanager
    async def session(
        self, server: ServerName, token: str, *, with_course_port: bool = False
    ) -> AsyncIterator[ClientSession]:
        """Serve and open one client session."""
        async with self.serve(with_course_port=with_course_port) as running:
            async with running.session(server, token) as session:
                yield session


@pytest.fixture
def mcp_settings(settings: Settings) -> Settings:
    """Settings whose MCP URL is http://testserver/mcp."""
    urls = settings.urls.model_copy(update={"mcp": f"{BASE_URL}/mcp"})
    return settings.model_copy(update={"urls": urls})


@pytest.fixture
def world(
    mcp_settings: Settings, clock: FixedClock, redis: FakeRedis, i18n: I18nCore
) -> World:
    """A fresh world of fakes."""
    return World(settings=mcp_settings, clock=clock, redis=redis, i18n=i18n)


def as_dict(value: Any) -> dict[str, Any]:
    """Narrow a structured tool result to a dict."""
    assert isinstance(value, dict)
    return value
