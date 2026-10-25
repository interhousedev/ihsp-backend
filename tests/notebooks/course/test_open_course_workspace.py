"""LMS-AI 3.1/4: opening the workspace of a course, and the public API for the AI."""

from uuid import UUID

from app.modules.notebooks.application.open_course_workspace import (
    FALLBACK_TITLE,
    WORKSPACE_EMOJI,
    workspace_title,
)
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    NotebookOrigin,
)
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_artifact, make_notebook, new_notebook_entity
from tests.fakes.notebooks.lms_workspace import EDIT, FakeLmsWorkspace, WorkspaceCourse

import pytest


async def test_the_first_editor_creates_the_workspace(
    services: NotebooksServices, teacher: Actor, course: WorkspaceCourse
) -> None:
    """LMS-AI 3.1: get-or-create; the creator owns it; the course names it."""
    opened = await services.open_course_workspace.execute(teacher, course.id)

    notebook = opened.notebook
    assert opened.created and opened.can_write
    assert notebook.is_course_workspace
    assert (notebook.course_id, notebook.owner_id) == (course.id, teacher.user_id)
    assert (notebook.title, notebook.emoji) == ("Physics 9", WORKSPACE_EMOJI)
    assert not notebook.title_auto and not notebook.emoji_auto
    assert notebook.chat_config.language.value == "auto"


async def test_every_member_gets_the_same_workspace(
    services: NotebooksServices,
    teacher: Actor,
    editor: Actor,
    viewer: Actor,
    course: WorkspaceCourse,
) -> None:
    """LMS-AI 3.1: one workspace per course; a reader gets it read-only."""
    first = await services.open_course_workspace.execute(teacher, course.id)

    again = await services.open_course_workspace.execute(editor, course.id)
    read_only = await services.open_course_workspace.execute(viewer, course.id)

    assert again.notebook.id == read_only.notebook.id == first.notebook.id
    assert (again.created, again.can_write) == (False, True)
    assert (read_only.created, read_only.can_write) == (False, False)
    assert again.notebook.owner_id == teacher.user_id


async def test_a_reader_cannot_create_the_workspace(
    services: NotebooksServices, viewer: Actor, course: WorkspaceCourse
) -> None:
    """LMS-AI 4: `view_drafts` without a workspace yet gets a 404."""
    with pytest.raises(NotebookNotFoundError):
        await services.open_course_workspace.execute(viewer, course.id)


@pytest.mark.parametrize("who", ["reviewer", "stranger", "student"])
async def test_outsiders_cannot_open_it(
    services: NotebooksServices,
    course: WorkspaceCourse,
    request: pytest.FixtureRequest,
    who: str,
) -> None:
    """LMS-AI 3.1: strangers look the same as an unknown course."""
    actor: Actor = request.getfixturevalue(who)

    with pytest.raises(NotebookNotFoundError):
        await services.open_course_workspace.execute(actor, course.id)


async def test_an_unknown_course_looks_like_a_foreign_one(
    services: NotebooksServices, teacher: Actor
) -> None:
    """LMS-AI 3.1: no course, no workspace, no difference to a stranger."""
    with pytest.raises(NotebookNotFoundError):
        await services.open_course_workspace.execute(teacher, UUID(int=7))


async def test_a_lost_race_reads_the_winners_workspace(
    services: NotebooksServices,
    uow_factory: UowFactory,
    editor: Actor,
    teacher: Actor,
    course: WorkspaceCourse,
) -> None:
    """LMS-AI 3.1: the unique index decides; the second insert gets False."""
    winner = new_notebook_entity(
        editor.user_id, origin=NotebookOrigin.COURSE, course_id=course.id
    )
    loser = new_notebook_entity(
        teacher.user_id, origin=NotebookOrigin.COURSE, course_id=course.id
    )
    async with uow_factory() as uow:
        assert await uow.notebooks.add_workspace(winner)
        assert not await uow.notebooks.add_workspace(loser)
        await uow.commit()

    opened = await services.open_course_workspace.execute(teacher, course.id)

    assert (opened.notebook.id, opened.created) == (winner.id, False)


def test_the_title_is_the_course_title_on_one_line_and_cut() -> None:
    """LMS-AI 3.1: clean title rules, at most 120 characters."""
    assert workspace_title("  Physics \n 9 ") == "Physics 9"
    assert len(workspace_title("x" * 300)) == 120
    assert workspace_title("   ") == FALLBACK_TITLE


# - - - Public API (the author assistant) - - -


async def test_the_queries_find_the_workspace_for_members_only(
    services: NotebooksServices,
    workspace: Notebook,
    course: WorkspaceCourse,
    viewer: Actor,
    stranger: Actor,
) -> None:
    """LMS-AI 2: `NotebooksQueries.course_workspace`."""
    found = await services.public.course_workspace(viewer.user_id, course.id)

    assert found == {
        "id": str(workspace.id),
        "title": "Physics 9",
        "course_id": str(course.id),
        "can_write": False,
    }
    assert await services.public.course_workspace(stranger.user_id, course.id) is None


async def test_the_queries_answer_none_before_the_workspace_exists(
    services: NotebooksServices, course: WorkspaceCourse, teacher: Actor
) -> None:
    """LMS-AI 2: no workspace yet is None, not an error."""
    assert await services.public.course_workspace(teacher.user_id, course.id) is None


async def test_the_command_opens_the_workspace(
    services: NotebooksServices, course: WorkspaceCourse, editor: Actor
) -> None:
    """LMS-AI 2: `NotebooksCommands.open_course_workspace` returns the dict."""
    opened = await services.commands.open_course_workspace(editor, course.id)

    assert set(opened) == {"id", "title", "course_id", "can_write"}
    assert (opened["course_id"], opened["can_write"]) == (str(course.id), True)


async def test_the_queries_read_a_ready_output_of_the_workspace(
    services: NotebooksServices,
    uow_factory: UowFactory,
    workspace: Notebook,
    viewer: Actor,
    stranger: Actor,
) -> None:
    """LMS-AI 2: `get_artifact_content` for members; None when not ready or foreign."""
    ready = await make_artifact(uow_factory, workspace, ArtifactKind.REPORT)
    queued = await make_artifact(
        uow_factory, workspace, ArtifactKind.REPORT, ArtifactStatus.QUEUED
    )
    public = services.public

    content = await public.get_artifact_content(viewer.user_id, workspace.id, ready.id)

    assert content is not None
    assert content["content"] == {"markdown": "# Report\n\nText."}
    assert (content["kind"], content["status"]) == ("report", "ready")
    assert (
        await public.get_artifact_content(viewer.user_id, workspace.id, queued.id)
        is None
    )
    assert (
        await public.get_artifact_content(stranger.user_id, workspace.id, ready.id)
        is None
    )


async def test_the_assistant_tools_read_the_workspace_as_a_member(
    services: NotebooksServices,
    workspace: Notebook,
    ws_source: object,
    editor: Actor,
    stranger: Actor,
) -> None:
    """LMS-AI 3.1: get_notebook/search/list_artifacts work for members only."""
    public = services.public

    detail = await public.get_notebook(editor.user_id, workspace.id)
    hits = await public.search(editor.user_id, workspace.id, "force", 5)

    assert detail is not None and detail["title"] == "Physics 9"
    assert hits
    assert await public.get_notebook(stranger.user_id, workspace.id) is None
    assert await public.search(stranger.user_id, workspace.id, "force", 5) == []


async def test_a_students_list_never_shows_a_workspace(
    services: NotebooksServices,
    uow_factory: UowFactory,
    lms_ws: FakeLmsWorkspace,
    course: WorkspaceCourse,
    student: Actor,
) -> None:
    """LMS-AI 3.1: even a workspace owned by a student-staff member is not listed."""
    lms_ws.grant(course, student.user_id, EDIT)
    await services.open_course_workspace.execute(student, course.id)
    own = await make_notebook(uow_factory, student.user_id, title="Mine")

    page = await services.list_notebooks.execute(student)
    listed = await services.public.list_notebooks(student.user_id)

    assert [n.id for n in page.items] == [own.id]
    assert [n["id"] for n in listed] == [str(own.id)]
