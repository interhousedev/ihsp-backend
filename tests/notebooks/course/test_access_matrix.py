"""LMS-AI 3.1: who may read and write a course workspace, use case by use case.

Editors (`edit`) read and write, readers (`view_drafts`) only read, everyone else
(another permission, a stranger, a student, a member who lost the permission) gets
the 404 of a missing notebook. Rows always carry the workspace owner's id; chat
threads and progress stay the acting user's own.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.modules.notebooks.domain.entities import Artifact, Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import (
    NotebookNotFoundError,
    WorkspaceActionError,
    WorkspaceReadOnlyError,
)
from app.modules.notebooks.domain.source_input import TextInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_artifact
from tests.fakes.notebooks.lms_workspace import FakeLmsWorkspace, WorkspaceCourse

import pytest


@dataclass(frozen=True, slots=True)
class Ctx:
    """What an operation needs: the services and the rows of the workspace."""

    services: NotebooksServices
    notebook: Notebook
    source: Source
    artifact: Artifact


Op = Callable[[Ctx, Actor], Awaitable[Any]]

READS: dict[str, Op] = {
    "get_notebook": lambda c, a: c.services.get_notebook.execute(a, c.notebook.id),
    "list_sources": lambda c, a: c.services.list_sources.execute(a, c.notebook.id),
    "get_source": lambda c, a: c.services.get_source.execute(
        a, c.notebook.id, c.source.id
    ),
    "list_passages": lambda c, a: c.services.list_passages.execute(
        a, c.notebook.id, c.source.id
    ),
    "search_sources": lambda c, a: c.services.search_sources.execute(
        a, c.notebook.id, "newton"
    ),
    "list_artifacts": lambda c, a: c.services.list_artifacts.execute(a, c.notebook.id),
    "get_artifact": lambda c, a: c.services.get_artifact.execute(
        a, c.notebook.id, c.artifact.id
    ),
    "get_chat": lambda c, a: c.services.get_chat.execute(a, c.notebook.id),
    "ask": lambda c, a: c.services.ask_notebook.execute(a, c.notebook.id, "Why?"),
    "usage": lambda c, a: c.services.get_notebook_usage.execute(a, c.notebook.id),
    "course_steps": lambda c, a: c.services.list_course_steps.execute(a, c.notebook.id),
}

WRITES: dict[str, Op] = {
    "update_notebook": lambda c, a: c.services.update_notebook.execute(
        a, c.notebook.id, {"pinned": True}
    ),
    "add_sources": lambda c, a: c.services.add_sources.execute(
        a, c.notebook.id, [TextInput(title="More", text="Momentum is m v.")]
    ),
    "update_source": lambda c, a: c.services.update_source.execute(
        a, c.notebook.id, c.source.id, {"title": "Renamed"}
    ),
    "select_sources": lambda c, a: c.services.select_sources.execute(
        a, c.notebook.id, True
    ),
    "remove_source": lambda c, a: c.services.remove_source.execute(
        a, c.notebook.id, c.source.id
    ),
    "request_artifact": lambda c, a: c.services.request_artifact.execute(
        a, c.notebook.id, ArtifactKind.MIND_MAP, {}, None
    ),
    "rename_artifact": lambda c, a: c.services.rename_artifact.execute(
        a, c.notebook.id, c.artifact.id, "Renamed"
    ),
    "delete_artifact": lambda c, a: c.services.delete_artifact.execute(
        a, c.notebook.id, c.artifact.id
    ),
    "save_as_source": lambda c, a: c.services.save_as_source.execute(
        a, c.notebook.id, c.artifact.id
    ),
}
EVERYTHING = {**READS, **WRITES}


@pytest.fixture
async def ctx(
    services: NotebooksServices,
    uow_factory: UowFactory,
    workspace: Notebook,
    ws_source: Source,
) -> Ctx:
    """The workspace with a ready source and a ready report."""
    artifact = await make_artifact(uow_factory, workspace, ArtifactKind.REPORT)
    return Ctx(services, workspace, ws_source, artifact)


@pytest.mark.parametrize("name", sorted(EVERYTHING))
async def test_another_editor_may_do_everything(
    ctx: Ctx, editor: Actor, name: str
) -> None:
    """LMS-AI 3.1: `edit` reads and writes the workspace opened by someone else."""
    await EVERYTHING[name](ctx, editor)


@pytest.mark.parametrize("name", sorted(EVERYTHING))
async def test_the_owner_may_do_everything(ctx: Ctx, teacher: Actor, name: str) -> None:
    """LMS-AI 3.1: the editor who opened it first is just another editor."""
    await EVERYTHING[name](ctx, teacher)


@pytest.mark.parametrize("name", sorted(READS))
async def test_a_reader_may_read_and_ask(ctx: Ctx, viewer: Actor, name: str) -> None:
    """LMS-AI 3.1: `view_drafts` opens the workspace and asks in its own thread."""
    await READS[name](ctx, viewer)


@pytest.mark.parametrize("name", sorted(WRITES))
async def test_a_reader_may_not_write(ctx: Ctx, viewer: Actor, name: str) -> None:
    """LMS-AI 3.1: `view_drafts` gets 403 workspace-readonly for every change."""
    with pytest.raises(WorkspaceReadOnlyError):
        await WRITES[name](ctx, viewer)


@pytest.mark.parametrize("who", ["reviewer", "stranger", "student"])
@pytest.mark.parametrize("name", sorted(EVERYTHING))
async def test_everyone_else_sees_no_notebook(
    ctx: Ctx, request: pytest.FixtureRequest, who: str, name: str
) -> None:
    """LMS-AI 3.1: another permission, a stranger or a student get the 404."""
    actor: Actor = request.getfixturevalue(who)

    with pytest.raises(NotebookNotFoundError):
        await EVERYTHING[name](ctx, actor)


@pytest.mark.parametrize("name", ["get_notebook", "add_sources", "ask"])
async def test_a_removed_member_loses_access_at_once(
    ctx: Ctx,
    editor: Actor,
    lms_ws: FakeLmsWorkspace,
    course: WorkspaceCourse,
    name: str,
) -> None:
    """LMS-AI 3.1: the permission is checked on every call, not when opened."""
    await READS["get_notebook"](ctx, editor)
    lms_ws.grant(course, editor.user_id, ())

    with pytest.raises(NotebookNotFoundError):
        await EVERYTHING[name](ctx, editor)


async def test_rows_added_by_an_editor_belong_to_the_workspace(
    ctx: Ctx, editor: Actor, teacher: Actor
) -> None:
    """LMS-AI 3.1: a source added by another editor carries the owner's id."""
    added = await WRITES["add_sources"](ctx, editor)

    assert [source.owner_id for source in added.items] == [teacher.user_id]
    listed = await ctx.services.list_sources.execute(teacher, ctx.notebook.id)
    assert {source.id for source in listed} >= {added.items[0].id}


async def test_an_output_asked_by_an_editor_is_charged_to_them(
    ctx: Ctx, editor: Actor, teacher: Actor
) -> None:
    """LMS-AI 3.1: the output belongs to the workspace, the request to the editor."""
    artifact = await WRITES["request_artifact"](ctx, editor)

    assert artifact.owner_id == teacher.user_id
    assert artifact.requested_by == editor.user_id
    assert artifact.charged_to == editor.user_id


async def test_each_member_has_an_own_chat_thread(
    ctx: Ctx, editor: Actor, viewer: Actor
) -> None:
    """LMS-AI 3.1: chat messages are per acting user, never shared."""
    await ctx.services.ask_notebook.execute(editor, ctx.notebook.id, "What is F?")

    mine = await ctx.services.get_chat.execute(editor, ctx.notebook.id)
    theirs = await ctx.services.get_chat.execute(viewer, ctx.notebook.id)

    assert [m.user_id for m in mine] == [editor.user_id] * 2
    assert theirs == []


async def test_a_reader_sees_that_it_may_not_write(ctx: Ctx, viewer: Actor) -> None:
    """LMS-AI 4: `NotebookDetail.can_write` is False for `view_drafts`."""
    opened = await ctx.services.get_notebook.execute(viewer, ctx.notebook.id)

    assert (opened.course_id, opened.can_write) == (ctx.notebook.course_id, False)


@pytest.mark.parametrize("action", ["delete", "copy", "flashcards"])
async def test_a_workspace_cannot_be_deleted_copied_or_saved_as_a_set(
    ctx: Ctx, uow_factory: UowFactory, teacher: Actor, action: str
) -> None:
    """LMS-AI 3.1: deleting the workspace is not offered, nor are personal copies."""
    services, notebook_id = ctx.services, ctx.notebook.id
    deck = await make_artifact(uow_factory, ctx.notebook, ArtifactKind.FLASHCARDS)
    calls: dict[str, Callable[[], Awaitable[object]]] = {
        "delete": lambda: services.delete_notebook.execute(teacher, notebook_id),
        "copy": lambda: services.copy_notebook.execute(teacher, notebook_id),
        "flashcards": lambda: services.save_flashcard_set.execute(
            teacher, notebook_id, deck.id
        ),
    }

    with pytest.raises(WorkspaceActionError):
        await calls[action]()
