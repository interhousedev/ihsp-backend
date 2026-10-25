"""Fixtures of the course workspace tests: course staff, the gate and the module."""

import asyncio
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.infrastructure.lms_course_gate import LmsCourseGate
from app.modules.notebooks.infrastructure.uow import SqlNotebooksUnitOfWork
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.modules.notebooks.wiring import NotebooksServices, build
from app.modules.notebooks.wiring_core import CoreOverrides
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import ClassworkQueries, ScheduleQueries
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import LmsSourceReader, LmsWorkspace
from app.shared.db.uow_testing import noop_audit_writer
from app.shared.notifications import NotificationDraft
from app.shared.wiring import ModuleDeps
from tests.factories.notebooks import make_source
from tests.fakes.ai.contracts import FakeIdentity, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.fakes.notebooks.lms_workspace import (
    EDIT,
    REVIEW,
    VIEW,
    FakeLmsWorkspace,
    WorkspaceCourse,
)
from tests.fakes.notebooks.world import World

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SOURCE_TEXTS = (
    "Newton's first law: a body keeps its state of motion unless a force acts on it.",
    "Newton's second law: the force equals mass times acceleration, F = m a.",
    "Newton's third law: every action has an equal and opposite reaction.",
)


@pytest.fixture
def clock() -> FixedClock:
    """A fixed clock close to the real time (budget windows expire in Redis)."""
    return FixedClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def lms_ws() -> FakeLmsWorkspace:
    """The LMS side of the course workspaces."""
    return FakeLmsWorkspace()


@pytest.fixture
def teacher(make_actor: Callable[..., Actor]) -> Actor:
    """The course editor who opens the workspace first (its owner)."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def editor(make_actor: Callable[..., Actor]) -> Actor:
    """A second editor of the course."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def viewer(make_actor: Callable[..., Actor]) -> Actor:
    """A member who may only read the drafts (`view_drafts`)."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def reviewer(make_actor: Callable[..., Actor]) -> Actor:
    """A member whose permission does not open the workspace."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def stranger(make_actor: Callable[..., Actor]) -> Actor:
    """A teacher who is not on the course staff."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def course(
    lms_ws: FakeLmsWorkspace,
    teacher: Actor,
    editor: Actor,
    viewer: Actor,
    reviewer: Actor,
) -> WorkspaceCourse:
    """A course with two editors, a viewer and a reviewer, and one draft step."""
    course = lms_ws.add_course("Physics 9", "Mechanics for grade 9")
    lms_ws.grant(course, teacher.user_id, EDIT)
    lms_ws.grant(course, editor.user_id, EDIT)
    lms_ws.grant(course, viewer.user_id, VIEW)
    lms_ws.grant(course, reviewer.user_id, REVIEW)
    lms_ws.add_step(course, "Newton's laws")
    return course


@pytest.fixture
def identity(
    student: Actor,
    other_student: Actor,
    teacher: Actor,
    editor: Actor,
    viewer: Actor,
    reviewer: Actor,
    stranger: Actor,
) -> FakeIdentity:
    """Every user of the tests (locale `en`)."""
    users = [
        dataclasses.replace(make_user(Role.STUDENT), id=actor.user_id)
        for actor in (student, other_student, teacher, editor, viewer, reviewer)
    ]
    users.append(dataclasses.replace(make_user(Role.TEACHER), id=stranger.user_id))
    return FakeIdentity(*users)


@pytest.fixture
def outbox() -> list[NotificationDraft]:
    """The notifications written by committed transactions."""
    return []


@pytest.fixture
def uow_factory(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    settings: Settings,
    lms_ws: FakeLmsWorkspace,
    outbox: list[NotificationDraft],
) -> UowFactory:
    """SQL units of work whose course gate asks the fake LMS."""
    gate = LmsCourseGate(cast(LmsWorkspace, lms_ws), settings)

    async def write_outbox(
        session: AsyncSession, drafts: list[NotificationDraft]
    ) -> None:
        outbox.extend(drafts)

    def factory() -> NotebooksUnitOfWork:
        return SqlNotebooksUnitOfWork(
            sessionmaker_in_tx, write_outbox, noop_audit_writer, course_gate=gate
        )

    return factory


@pytest.fixture
def world() -> World:
    """Empty fakes of files, chats, lessons, flash cards, LMS and the web."""
    return World()


@pytest.fixture
def services(
    module_deps: ModuleDeps,
    scripted_llm: ScriptedLlm,
    identity: FakeIdentity,
    uow_factory: UowFactory,
    world: World,
    lms_ws: FakeLmsWorkspace,
) -> NotebooksServices:
    """The whole module with course workspaces over the fakes."""

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
        fetcher=world.fetcher,
        classwork=cast(ClassworkQueries, world.classwork),
        terms=world.terms,
        overrides=CoreOverrides(uow_factory=uow_factory),
        sleep=no_sleep,
        workspace=cast(LmsWorkspace, lms_ws),
    )


@pytest.fixture
async def workspace(
    services: NotebooksServices, teacher: Actor, course: WorkspaceCourse
) -> Notebook:
    """The course workspace, opened first by `teacher` (its owner)."""
    opened = await services.open_course_workspace.execute(teacher, course.id)
    return opened.notebook


@pytest.fixture
async def ws_source(uow_factory: UowFactory, workspace: Notebook) -> Source:
    """A ready, selected text source of the workspace."""
    return await make_source(
        uow_factory, workspace, title="Mechanics notes", texts=SOURCE_TEXTS
    )
