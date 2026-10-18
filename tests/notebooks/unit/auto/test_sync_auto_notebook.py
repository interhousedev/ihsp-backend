"""NB-AUTO: the job that keeps a subject or lesson notebook in step with the lessons."""

import dataclasses
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import (
    NotebookOrigin,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.domain.source_input import NoteInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_auto import AutoServices
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.contracts.academic import LessonRef
from tests.fakes.ai.contracts import make_file, make_lesson
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.links import make_resource
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.auto.conftest import (
    PAGE,
    open_subject,
    student_file,
    teacher_file,
)

import pytest


async def _keys(uow_factory: UowFactory, notebook_id: UUID) -> list[str | None]:
    async with uow_factory() as uow:
        return [s.ref_key for s in await uow.sources.list_for_notebook(notebook_id)]


async def _source(uow_factory: UowFactory, notebook_id: UUID, link: str) -> Source:
    async with uow_factory() as uow:
        found = [
            s
            for s in await uow.sources.list_for_notebook(notebook_id)
            if s.ref_key == f"lesson:{link}"
        ]
    assert len(found) == 1
    return found[0]


async def test_a_material_added_later_comes_in_with_the_next_sync(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
    kicker: FakeTaskKicker,
) -> None:
    """NB-AUTO: new teacher materials appear in the notebook without any action."""
    first = teacher_file(world, physics, "First")
    notebook = await open_subject(auto, student, physics)
    second = teacher_file(world, physics, "Second")
    kicker.calls.clear()

    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert (result.added, result.removed) == (1, 0)
    assert await _keys(uow_factory, notebook.id) == [
        f"lesson:{first}",
        f"lesson:{second}",
    ]
    added = await _source(uow_factory, notebook.id, second)
    assert added.status is SourceStatus.PENDING and added.selected
    assert kicker.calls == [("notebooks.process_source", {"source_id": str(added.id)})]


async def test_a_sync_with_nothing_new_changes_nothing(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
    kicker: FakeTaskKicker,
) -> None:
    """NB-AUTO: running the job twice is harmless."""
    teacher_file(world, physics)
    notebook = await open_subject(auto, student, physics)
    before = await _keys(uow_factory, notebook.id)
    kicker.calls.clear()

    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert (result.added, result.removed) == (0, 0)
    assert await _keys(uow_factory, notebook.id) == before
    assert kicker.calls == []


async def test_a_material_the_teacher_hides_leaves_the_notebook(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: only materials the student can see stay in the notebook."""
    keep = teacher_file(world, physics, "Keep")
    hide = teacher_file(world, physics, "Hide")
    notebook = await open_subject(auto, student, physics)
    [resource] = [r for r in world.links.items[physics.id] if str(r.link_id) == hide]
    world.links.items[physics.id].remove(resource)
    world.links.items[physics.id].append(
        make_resource(physics.id, title="Hide", hidden=True)
    )

    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert result.removed == 1
    assert await _keys(uow_factory, notebook.id) == [f"lesson:{keep}"]


async def test_materials_of_a_lesson_the_student_left_are_dropped(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: when the student leaves the audience the materials go."""
    lesson_link = teacher_file(world, physics)
    notebook = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.LESSON_AUTO, physics.id
    )
    assert await _keys(uow_factory, notebook.id) == [f"lesson:{lesson_link}"]
    world.schedule.audience.discard((student.user_id, physics.id))

    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert result.removed == 1 and await _keys(uow_factory, notebook.id) == []


async def test_the_students_own_file_comes_in_but_classmates_files_need_the_switch(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: own attachments are the student's; classmates' wait for the toggle."""
    world.schedule.attend(other_student.user_id, physics)
    mine = student_file(world, physics, student, "Mine")
    theirs = student_file(world, physics, other_student, "Theirs")

    notebook = await open_subject(auto, student, physics)

    assert await _keys(uow_factory, notebook.id) == [f"lesson:{mine}"]
    own = await _source(uow_factory, notebook.id, mine)
    assert own.origin is not None and "from_classmates" not in own.origin

    await auto.update_auto_settings.execute(
        student, notebook.id, {"include_classmates": True}
    )

    assert await _keys(uow_factory, notebook.id) == [
        f"lesson:{mine}",
        f"lesson:{theirs}",
    ]
    classmate = await _source(uow_factory, notebook.id, theirs)
    assert classmate.origin is not None
    assert classmate.origin["from_classmates"] is True
    assert classmate.origin["author"] == "Bobur"


async def test_switching_classmates_off_removes_their_files(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: the toggle works both ways."""
    world.schedule.attend(other_student.user_id, physics)
    student_file(world, physics, other_student)
    notebook = await open_subject(auto, student, physics)
    await auto.update_auto_settings.execute(
        student, notebook.id, {"include_classmates": True}
    )
    assert (await _stored(uow_factory, notebook.id)).source_count == 1

    await auto.update_auto_settings.execute(
        student, notebook.id, {"include_classmates": False}
    )

    assert (await _stored(uow_factory, notebook.id)).source_count == 0


async def _stored(uow_factory: UowFactory, notebook_id: UUID) -> Notebook:
    async with uow_factory() as uow:
        found = await uow.notebooks.get(notebook_id)
    assert found is not None
    return found


async def test_a_file_without_readable_text_is_picked_up_later(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: a file still being processed is skipped, not an error."""
    ref = world.files.add_text(make_file(physics.id, name="Late.pdf"), PAGE)
    world.files.drop_text(ref.id)
    resource = world.links.add(make_resource(physics.id, title="Late", file_id=ref.id))
    notebook = await open_subject(auto, student, physics)
    assert notebook.source_count == 0

    world.files.add_text(ref, PAGE)
    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert result.added == 1
    assert await _keys(uow_factory, notebook.id) == [f"lesson:{resource.link_id}"]


async def test_the_notebook_keeps_the_best_materials_when_it_is_full(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
    sources: SourcesServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NB-AUTO: at the source limit teacher materials win over classmates' files."""
    world.schedule.attend(other_student.user_id, physics)
    theirs = student_file(world, physics, other_student, "Theirs")
    material_a = teacher_file(world, physics, "A")
    material_b = teacher_file(world, physics, "B")
    notebook = await open_subject(auto, student, physics)
    await auto.update_auto_settings.execute(
        student, notebook.id, {"include_classmates": True}
    )
    assert (await _stored(uow_factory, notebook.id)).source_count == 3
    settings = auto.sync_auto_notebook.settings
    monkeypatch.setattr(
        auto.sync_auto_notebook,
        "settings",
        settings.model_copy(
            update={
                "notebooks": settings.notebooks.model_copy(update={"max_sources": 2})
            }
        ),
    )

    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert result.removed == 1
    kept = await _keys(uow_factory, notebook.id)
    assert f"lesson:{theirs}" not in kept
    assert set(kept) == {f"lesson:{material_a}", f"lesson:{material_b}"}


async def test_notes_in_the_notebook_are_never_touched_and_take_up_room(
    auto: AutoServices,
    uow_factory: UowFactory,
    sources: SourcesServices,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: the student's notes survive every sync."""
    teacher_file(world, physics)
    notebook = await open_subject(auto, student, physics)
    note = await sources.add_sources.execute(
        student, notebook.id, [NoteInput(title="My note", body_md="Remember this.")]
    )

    await auto.sync_auto_notebook.execute(notebook.id)

    async with uow_factory() as uow:
        left = await uow.sources.list_for_notebook(notebook.id)
    assert note.items[0].id in {s.id for s in left}
    assert {s.kind for s in left} == {SourceKind.LESSON_RESOURCE, SourceKind.NOTE}


async def test_deleted_and_manual_notebooks_are_left_alone(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
    notebook: Notebook,
) -> None:
    """NB-AUTO: the job does nothing for a manual notebook or a deleted one."""
    teacher_file(world, physics)
    auto_notebook = await open_subject(auto, student, physics)

    manual = await auto.sync_auto_notebook.execute(notebook.id)
    async with uow_factory() as uow:
        stored = await uow.notebooks.get(auto_notebook.id)
        assert stored is not None
        stored.deleted_at = stored.created_at
        await uow.notebooks.save(stored)
        await uow.commit()
    deleted = await auto.sync_auto_notebook.execute(auto_notebook.id)

    assert (manual.added, deleted.added) == (0, 0)


async def test_a_sync_records_when_it_ran(
    auto: AutoServices,
    world: World,
    student: Actor,
    physics: LessonRef,
    clock: FixedClock,
    uow_factory: UowFactory,
) -> None:
    """NB-AUTO: the time of the last sync decides when opening syncs again."""
    notebook = await open_subject(auto, student, physics)
    clock.advance(minutes=30)

    await auto.sync_auto_notebook.execute(notebook.id)

    assert (await _stored(uow_factory, notebook.id)).auto_synced_at == clock.now()


async def test_a_new_lesson_of_the_subject_adds_its_materials(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: lessons held later in the term feed the subject notebook too."""
    notebook = await open_subject(auto, student, physics)
    later = world.schedule.attend(
        student.user_id,
        make_lesson(subject="Physics", subject_id=physics.subject_id),
    )
    link = teacher_file(world, later, "New topic")

    await auto.sync_auto_notebook.execute(notebook.id)

    assert await _keys(uow_factory, notebook.id) == [f"lesson:{link}"]


async def test_a_material_is_titled_with_its_lesson_day(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: a material reads "DD.MM <original name>", the lesson's day first."""
    teacher_file(world, physics, "Classwork: Waves")
    notebook = await open_subject(auto, student, physics)

    async with uow_factory() as uow:
        titles = [s.title for s in await uow.sources.list_for_notebook(notebook.id)]

    assert titles == [f"{physics.date:%d.%m} Classwork: Waves"]


async def test_a_second_sync_counts_the_materials_already_there(
    auto: AutoServices,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: a sync with nothing new reports the present materials, adds none."""
    teacher_file(world, physics, "First")
    notebook = await open_subject(auto, student, physics)

    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert (result.added, result.removed, result.present) == (0, 0, 1)


async def test_a_file_still_processing_keeps_the_notebook_due_for_the_sweep(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
    clock: FixedClock,
) -> None:
    """NB-AUTO: a file still being processed is skipped and the notebook stays due.

    The upload finishes after the sync that the lesson's import kicked; nothing else
    would bring the file in, so the notebook must not be marked as synced.
    """
    late = make_file(physics.id, name="Late.pdf", status="processing", text_bytes=None)
    ref = world.files.add_text(late, PAGE)
    world.links.add(make_resource(physics.id, title="Late", file_id=ref.id))
    notebook = await open_subject(auto, student, physics)
    synced_at = (await _stored(uow_factory, notebook.id)).auto_synced_at
    clock.advance(minutes=30)

    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert (result.added, result.skipped) == (0, 1)
    assert (await _stored(uow_factory, notebook.id)).auto_synced_at == synced_at

    world.files.add_text(
        dataclasses.replace(late, status="ready", text_bytes=2000), PAGE
    )
    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert result.added == 1
    assert (await _stored(uow_factory, notebook.id)).auto_synced_at == clock.now()
