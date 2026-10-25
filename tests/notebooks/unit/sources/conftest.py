"""Fixtures of the source tests: the use cases over fakes of the other modules."""

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.ports.transcript import TranscriptProvider
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import CoreOverrides, build_core
from app.modules.notebooks.wiring_sources import SourcesServices, build_sources
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.library import LibrarySourceReader
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import LmsSourceReader
from app.shared.wiring import ModuleDeps
from tests.factories.notebooks import make_notebook
from tests.fakes.ai.contracts import FakeIdentity, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.sources.support import HookedLlm

import pytest


@pytest.fixture
def clock() -> FixedClock:
    """A fixed clock close to the real time.

    The budget session window expires at `now + 5 h` through Redis `EXPIREAT`,
    and Redis drops a key whose expiry is already in the past, so the default
    moment of 2026-10-06 would erase the session counters once that day is over.
    """
    return FixedClock(datetime.now(UTC).replace(microsecond=0))


Build = Callable[..., SourcesServices]


@pytest.fixture
def user_locale() -> str:
    """The locale of both students; parametrize it to test another language."""
    return "en"


@pytest.fixture
def identity(student: Actor, other_student: Actor, user_locale: str) -> FakeIdentity:
    """Users for the two students, with the locale of `user_locale`."""
    users = [
        dataclasses.replace(
            make_user(Role.STUDENT, locale=user_locale), id=actor.user_id
        )
        for actor in (student, other_student)
    ]
    return FakeIdentity(*users)


@pytest.fixture
def scripted_llm() -> HookedLlm:
    """The light model: scripted answers, the deterministic fake otherwise."""
    return HookedLlm()


@pytest.fixture
def world() -> World:
    """Empty fakes of files, chats, lessons, flash cards, LMS and the web."""
    return World()


@pytest.fixture
def sleeps() -> list[float]:
    """The pauses between provider retries (nobody really sleeps)."""
    return []


@pytest.fixture
def build(
    module_deps: ModuleDeps,
    scripted_llm: HookedLlm,
    identity: FakeIdentity,
    uow_factory: UowFactory,
    world: World,
    sleeps: list[float],
) -> Build:
    """Build the source services, optionally with other settings or fewer fakes."""

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def make(
        *,
        notebooks: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
        lms: bool = True,
        fetcher: bool = True,
        library: bool = True,
    ) -> SourcesServices:
        settings = module_deps.settings
        changed: dict[str, Any] = {}
        if notebooks:
            changed["notebooks"] = settings.notebooks.model_copy(update=notebooks)
        if limits:
            changed["limits"] = settings.limits.model_copy(update=limits)
        deps = dataclasses.replace(
            module_deps, settings=settings.model_copy(update=changed)
        )
        core = build_core(
            deps,
            gateway=scripted_llm,
            identity=cast(IdentityDirectory, identity),  # the locale lookup only
            overrides=CoreOverrides(uow_factory=uow_factory),
        )
        return build_sources(
            core,
            files=cast(FilesApi, world.files),
            ai=cast(AiQueries, world.chats),
            links=cast(LinksApi, world.links),
            schedule=cast(ScheduleQueries, world.schedule),
            flashcards=cast(FlashcardsApi, world.flashcards),
            lms=cast(LmsSourceReader, world.lms) if lms else None,
            fetcher=world.fetcher if fetcher else None,
            transcripts=cast(TranscriptProvider, world.transcripts),
            library=cast(LibrarySourceReader, world.library) if library else None,
            identity=cast(IdentityDirectory, identity),  # the owner's roles only
            sleep=sleep,
        )

    return make


@pytest.fixture
def sources(build: Build) -> SourcesServices:
    """The source use cases with the default limits."""
    return build()


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """An empty notebook of the student."""
    return await make_notebook(uow_factory, student.user_id, title="Biology")


@pytest.fixture
async def their_notebook(uow_factory: UowFactory, other_student: Actor) -> Notebook:
    """An empty notebook of the other student."""
    return await make_notebook(uow_factory, other_student.user_id, title="Chemistry")
