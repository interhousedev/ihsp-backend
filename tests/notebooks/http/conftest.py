"""Fixtures of the notebook HTTP tests: the real use cases behind the real routes."""

import asyncio
import dataclasses
from datetime import UTC, datetime
from typing import Any, cast

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.notebooks import ROUTERS
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices, build
from app.modules.notebooks.wiring_core import CoreOverrides
from app.shared.actor import Actor
from app.shared.contracts.academic import ClassworkQueries, ScheduleQueries
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.library import LibrarySourceReader
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import LmsSourceReader
from app.shared.wiring import ModuleDeps
from tests.fakes.ai.contracts import FakeIdentity
from tests.fakes.ai.web_search import WebRig
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.fakes.notebooks.world import World

import pytest
from httpx import AsyncClient


@pytest.fixture
def clock() -> FixedClock:
    """A fixed clock close to the real time (budget windows expire in Redis)."""
    return FixedClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def world() -> World:
    """Empty fakes of files, chats, lessons, flash cards, LMS and the web."""
    return World()


@pytest.fixture
def web(module_deps: ModuleDeps) -> WebRig:
    """The web search service over a scripted search (the search of the routes)."""
    return WebRig.build(module_deps.settings, module_deps.clock)


@pytest.fixture
def services(
    module_deps: ModuleDeps,
    scripted_llm: ScriptedLlm,
    identity: FakeIdentity,
    uow_factory: UowFactory,
    world: World,
    web: WebRig,
) -> NotebooksServices:
    """The whole module over the test transaction, fake Redis and the fakes."""

    async def no_sleep(seconds: float) -> None:
        await asyncio.sleep(0)

    return build(
        dataclasses.replace(module_deps),
        llm=scripted_llm,
        identity=cast(IdentityDirectory, identity),
        files=cast(FilesApi, world.files),
        ai=cast(AiQueries, world.chats),
        links=cast(LinksApi, world.links),
        schedule=cast(ScheduleQueries, world.schedule),
        flashcards=cast(FlashcardsApi, world.flashcards),
        lms=cast(LmsSourceReader, world.lms),
        library=cast(LibrarySourceReader, world.library),
        fetcher=world.fetcher,
        classwork=cast(ClassworkQueries, world.classwork),
        terms=world.terms,
        overrides=CoreOverrides(uow_factory=uow_factory),
        sleep=no_sleep,
        web_search=web.service,
    )


@pytest.fixture
def current(student: Actor) -> dict[str, Actor]:
    """The actor the next request runs as (replace `current["actor"]`)."""
    return {"actor": student}


@pytest.fixture
async def api(
    http_client: Any, services: NotebooksServices, current: dict[str, Actor]
) -> AsyncClient:
    """A client of the notebook routes whose requests run as `current["actor"]`."""
    client: AsyncClient = await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, notebooks=services
    )
    return client
