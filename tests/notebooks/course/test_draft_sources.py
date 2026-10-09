"""LMS-AI 4: the course's own draft steps as sources of its workspace."""

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    SourceForbiddenError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import (
    ChatInput,
    FileInput,
    LmsStepInput,
    SourceInput,
    TextInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook
from tests.fakes.ai.contracts import make_file
from tests.fakes.notebooks.lms_workspace import (
    DraftStep,
    FakeLmsWorkspace,
    WorkspaceCourse,
)
from tests.fakes.notebooks.world import World

import pytest


def _first_step(course: WorkspaceCourse) -> DraftStep:
    return course.sections[0].steps[0]


def _draft(course: WorkspaceCourse, step: DraftStep) -> LmsStepInput:
    return LmsStepInput(course_id=course.id, step_id=step.id, draft=True)


async def _add(
    services: NotebooksServices, actor: Actor, notebook: Notebook, item: SourceInput
) -> Source:
    """Add one item that must be accepted."""
    result = await services.add_sources.execute(actor, notebook.id, [item])
    assert not result.rejected, [r.error.code for r in result.rejected]
    return result.items[0]


async def _rejected(
    services: NotebooksServices, actor: Actor, notebook: Notebook, item: SourceInput
) -> Exception:
    """Add one item that must be refused; return why."""
    result = await services.add_sources.execute(actor, notebook.id, [item])
    assert not result.items
    return result.rejected[0].error


async def _stored(uow_factory: UowFactory, source: Source) -> Source:
    async with uow_factory() as uow:
        found = await uow.sources.get(source.id)
    assert found is not None
    return found


async def test_an_editor_adds_a_draft_step_of_the_course(
    services: NotebooksServices,
    uow_factory: UowFactory,
    workspace: Notebook,
    course: WorkspaceCourse,
    editor: Actor,
    teacher: Actor,
) -> None:
    """LMS-AI 4: `{kind: lms_step, course_id, step_id, draft: true}` is a source."""
    step = _first_step(course)

    source = await _add(services, editor, workspace, _draft(course, step))

    assert source.kind is SourceKind.LMS_STEP
    assert source.title == "Newton's laws"
    assert source.ref == {
        "course_id": str(course.id),
        "step_id": str(step.id),
        "draft": True,
    }
    assert source.ref_key == f"lms-draft:{step.id}"
    assert source.owner_id == teacher.user_id


async def test_the_draft_text_is_read_without_tests(
    services: NotebooksServices,
    uow_factory: UowFactory,
    workspace: Notebook,
    course: WorkspaceCourse,
    teacher: Actor,
) -> None:
    """LMS-AI 4, LMS-17: text and flash card blocks of the draft, no test answers."""
    source = await _add(
        services, teacher, workspace, _draft(course, _first_step(course))
    )

    await services.process_source.execute(source.id)

    ready = await _stored(uow_factory, source)
    async with uow_factory() as uow:
        passages = await uow.passages.list_for_sources([source.id])
    text = " ".join(p.text for p in passages)
    assert ready.status is SourceStatus.READY
    assert "F = m a" in text and "Newton" in text
    assert "correct" not in text


async def test_a_changed_draft_makes_the_source_outdated(
    services: NotebooksServices,
    uow_factory: UowFactory,
    workspace: Notebook,
    course: WorkspaceCourse,
    lms_ws: FakeLmsWorkspace,
    teacher: Actor,
) -> None:
    """LMS-AI 4: the draft hash is the version; the sweep marks a new draft stale."""
    step = _first_step(course)
    source = await _add(services, teacher, workspace, _draft(course, step))
    await services.process_source.execute(source.id)

    lms_ws.edit_step(step, "Momentum p = m v is kept in a closed system.")
    changed = await services.sweep_sources.execute()

    assert changed == 1
    assert (await _stored(uow_factory, source)).status is SourceStatus.STALE


async def test_sync_reads_the_new_draft(
    services: NotebooksServices,
    uow_factory: UowFactory,
    workspace: Notebook,
    course: WorkspaceCourse,
    lms_ws: FakeLmsWorkspace,
    teacher: Actor,
) -> None:
    """LMS-AI 4: "Sync" re-reads the draft like other synced sources."""
    step = _first_step(course)
    source = await _add(services, teacher, workspace, _draft(course, step))
    await services.process_source.execute(source.id)
    lms_ws.edit_step(step, "Momentum p = m v is kept in a closed system.")

    await services.sync_source.execute(teacher, workspace.id, source.id)
    await services.process_source.execute(source.id)

    async with uow_factory() as uow:
        passages = await uow.passages.list_for_sources([source.id])
    assert "Momentum" in " ".join(p.text for p in passages)


async def test_a_draft_of_another_course_is_refused(
    services: NotebooksServices,
    workspace: Notebook,
    lms_ws: FakeLmsWorkspace,
    teacher: Actor,
) -> None:
    """LMS-AI 4: only the workspace's own course."""
    other = lms_ws.add_course("Chemistry")
    step = lms_ws.add_step(other, "Atoms")

    error = await _rejected(services, teacher, workspace, _draft(other, step))

    assert isinstance(error, SourceForbiddenError)


async def test_a_live_step_is_not_a_workspace_source(
    services: NotebooksServices,
    workspace: Notebook,
    course: WorkspaceCourse,
    teacher: Actor,
) -> None:
    """LMS-AI 4: the workspace reads drafts; the live revision is for students."""
    step = _first_step(course)
    item = LmsStepInput(course_id=course.id, step_id=step.id)

    error = await _rejected(services, teacher, workspace, item)

    assert isinstance(error, SourceForbiddenError)


async def test_a_student_cannot_add_a_draft(
    services: NotebooksServices,
    uow_factory: UowFactory,
    course: WorkspaceCourse,
    student: Actor,
) -> None:
    """LMS-AI 4: drafts never reach a student's notebook."""
    own = await make_notebook(uow_factory, student.user_id)

    error = await _rejected(services, student, own, _draft(course, _first_step(course)))

    assert isinstance(error, SourceForbiddenError)


async def test_personal_objects_are_not_workspace_sources(
    services: NotebooksServices, workspace: Notebook, teacher: Actor
) -> None:
    """LMS-AI 3.1: a personal chat cannot be shared with the course staff."""
    error = await _rejected(services, teacher, workspace, ChatInput(chat_id=new_id()))

    assert isinstance(error, SourceUnsupportedError)
    assert error.params["hint"] == "workspace"


async def test_an_editor_adds_their_own_file(
    services: NotebooksServices,
    world: World,
    workspace: Notebook,
    editor: Actor,
    teacher: Actor,
) -> None:
    """LMS-AI 3.1: the file must be the acting editor's; the row is the workspace's."""
    mine = world.files.add_text(make_file(editor.user_id), "Kinematics notes.")
    theirs = world.files.add_text(make_file(teacher.user_id), "Owner's file.")

    added = await _add(services, editor, workspace, FileInput(file_id=mine.id))
    error = await _rejected(services, editor, workspace, FileInput(file_id=theirs.id))

    assert added.owner_id == teacher.user_id
    assert isinstance(error, SourceForbiddenError)


# - - - The step picker - - -


async def test_the_picker_lists_the_draft_outline(
    services: NotebooksServices,
    workspace: Notebook,
    course: WorkspaceCourse,
    lms_ws: FakeLmsWorkspace,
    viewer: Actor,
    teacher: Actor,
) -> None:
    """LMS-AI 4: sections and steps; `added` marks steps that are sources."""
    first = _first_step(course)
    second = lms_ws.add_step(course, "Friction", section="Forces")
    await _add(services, teacher, workspace, _draft(course, first))

    view = await services.list_course_steps.execute(viewer, workspace.id)

    titles = [
        (section.title, [step.title for step in section.steps])
        for section in view.brief.sections
    ]
    assert titles == [("Dynamics", ["Newton's laws"]), ("Forces", ["Friction"])]
    assert view.added == {first.id}
    assert second.id not in view.added


async def test_the_picker_is_for_workspaces_only(
    services: NotebooksServices, uow_factory: UowFactory, student: Actor
) -> None:
    """LMS-AI 4: a student's notebook has no course outline."""
    own = await make_notebook(uow_factory, student.user_id)

    with pytest.raises(InvalidOptionsError):
        await services.list_course_steps.execute(student, own.id)


async def test_pasted_text_works_in_a_workspace(
    services: NotebooksServices, workspace: Notebook, editor: Actor
) -> None:
    """LMS-AI 4: pasted text, notes and links work once access works."""
    source = await _add(
        services, editor, workspace, TextInput(title="Plan", text="Week 1: forces.")
    )

    assert source.kind is SourceKind.TEXT
