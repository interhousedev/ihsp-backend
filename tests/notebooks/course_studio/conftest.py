"""Fixtures of the course Studio tests: a course draft, a workspace, the services."""

import dataclasses
from collections.abc import Callable
from typing import cast

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore, build_core
from app.modules.notebooks.wiring_studio import (
    LmsApplyPorts,
    StudioServices,
    build_studio,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.lms import LmsDraftCommands, LmsQueries, LmsWorkspaceCommands
from app.shared.wiring import ModuleDeps
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.contracts import FakeFlashcards, FakeIdentity, make_user
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.fakes.notebooks.lms_apply import FakeCourseDraft
from tests.notebooks.unit.studio.helpers import SOURCE_TEXTS

import pytest


@pytest.fixture
def editor(make_actor: Callable[..., Actor]) -> Actor:
    """A teacher with `edit` on the course."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def reader(make_actor: Callable[..., Actor]) -> Actor:
    """A teacher with `view_drafts` only."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def stranger(make_actor: Callable[..., Actor]) -> Actor:
    """A teacher who is not staff of the course."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def draft(editor: Actor, reader: Actor) -> FakeCourseDraft:
    """A course draft with a section and a step in it."""
    course = FakeCourseDraft(editors=[editor.user_id], viewers=[reader.user_id])
    section = course.add_section("Light reactions")
    course.add_step(section, "Photons")
    return course


@pytest.fixture
def identity(editor: Actor, reader: Actor, stranger: Actor) -> FakeIdentity:
    """Users of the three teachers (locale `en`)."""
    users = [
        dataclasses.replace(make_user(Role.TEACHER), id=actor.user_id)
        for actor in (editor, reader, stranger)
    ]
    return FakeIdentity(*users)


@pytest.fixture
def scripted_llm() -> ScriptedLlm:
    """The model: scripted answers, the deterministic fake otherwise."""
    return ScriptedLlm()


@pytest.fixture
def core(
    module_deps: ModuleDeps,
    scripted_llm: ScriptedLlm,
    identity: FakeIdentity,
    draft: FakeCourseDraft,
) -> NotebooksCore:
    """The shared services with the course draft as the LMS workspace."""
    return build_core(
        module_deps,
        gateway=scripted_llm,
        identity=cast(IdentityDirectory, identity),
        workspace=draft,
    )


@pytest.fixture
def studio(core: NotebooksCore, draft: FakeCourseDraft) -> StudioServices:
    """The Studio services with the course draft behind "Apply to the course"."""

    async def no_wait(seconds: float) -> None:
        return None

    return build_studio(
        core,
        flashcards=cast(FlashcardsApi, FakeFlashcards()),
        sleep=no_wait,
        lms_apply=LmsApplyPorts(
            workspace=cast(LmsWorkspaceCommands, draft),
            queries=cast(LmsQueries, draft),
            drafts=cast(LmsDraftCommands, draft),
        ),
    )


@pytest.fixture
def uow_factory(core: NotebooksCore) -> UowFactory:
    """The unit of work of the services under test."""
    return core.uow_factory


@pytest.fixture
async def workspace(
    uow_factory: UowFactory, editor: Actor, draft: FakeCourseDraft
) -> Notebook:
    """The workspace notebook of the course, opened by the editor."""
    return await make_notebook(
        uow_factory,
        editor.user_id,
        title=draft.title,
        origin=NotebookOrigin.COURSE,
        course_id=draft.course_id,
    )


@pytest.fixture
async def source(uow_factory: UowFactory, workspace: Notebook) -> Source:
    """A ready source with four passages in the workspace."""
    return await make_source(
        uow_factory, workspace, title="Biology 10", texts=SOURCE_TEXTS
    )
