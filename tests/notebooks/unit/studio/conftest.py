"""Fixtures of the Studio tests: the services over the fakes, a notebook, a source."""

import dataclasses
from typing import Any, cast

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.infrastructure.uow import SqlNotebooksUnitOfWork
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.modules.notebooks.wiring_core import CoreOverrides, build_core
from app.modules.notebooks.wiring_studio import StudioServices, build_studio
from app.shared.actor import Actor
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.db.uow_testing import noop_audit_writer
from app.shared.notifications import NotificationDraft
from app.shared.wiring import ModuleDeps
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.contracts import FakeFlashcards, FakeIdentity
from tests.notebooks.unit.studio.helpers import SOURCE_TEXTS, Build, HookedLlm

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def outbox() -> list[NotificationDraft]:
    """The notifications written by committed transactions."""
    return []


@pytest.fixture
def uow_factory(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    outbox: list[NotificationDraft],
) -> UowFactory:
    """SQL units of work whose outbox writer records the drafts."""

    async def write_outbox(
        session: AsyncSession, drafts: list[NotificationDraft]
    ) -> None:
        outbox.extend(drafts)

    def factory() -> NotebooksUnitOfWork:
        return SqlNotebooksUnitOfWork(
            sessionmaker_in_tx, write_outbox, noop_audit_writer
        )

    return factory


@pytest.fixture
def scripted_llm() -> HookedLlm:
    """The model: scripted answers, the deterministic fake otherwise."""
    return HookedLlm()


@pytest.fixture
def flashcards() -> FakeFlashcards:
    """The flash card module."""
    return FakeFlashcards()


@pytest.fixture
def sleeps() -> list[float]:
    """The waits between provider retries (nobody really sleeps)."""
    return []


@pytest.fixture
def build(
    module_deps: ModuleDeps,
    scripted_llm: HookedLlm,
    identity: FakeIdentity,
    uow_factory: UowFactory,
    flashcards: FakeFlashcards,
    sleeps: list[float],
) -> Build:
    """Build the Studio services, optionally with other `limits` or `notebooks`."""

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def make(
        *, limits: dict[str, Any] | None = None, notebooks: dict[str, Any] | None = None
    ) -> StudioServices:
        settings = module_deps.settings
        changed: dict[str, Any] = {}
        if limits:
            changed["limits"] = settings.limits.model_copy(update=limits)
        if notebooks:
            changed["notebooks"] = settings.notebooks.model_copy(update=notebooks)
        deps = dataclasses.replace(
            module_deps, settings=settings.model_copy(update=changed)
        )
        core = build_core(
            deps,
            gateway=scripted_llm,
            identity=cast(IdentityDirectory, identity),  # the locale lookup only
            overrides=CoreOverrides(uow_factory=uow_factory),
        )
        return build_studio(
            core, flashcards=cast(FlashcardsApi, flashcards), sleep=sleep
        )

    return make


@pytest.fixture
def studio(build: Build) -> StudioServices:
    """The Studio services with the default limits."""
    return build()


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id, title="Biology")


@pytest.fixture
async def source(uow_factory: UowFactory, notebook: Notebook) -> Source:
    """A ready, selected source with four passages."""
    return await make_source(
        uow_factory, notebook, title="Biology 10", texts=SOURCE_TEXTS
    )
