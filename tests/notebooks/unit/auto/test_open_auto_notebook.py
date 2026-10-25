"""NB-AUTO: get-or-create of the subject and lesson notebooks."""

import datetime as dt
from datetime import timedelta
from typing import cast
from uuid import UUID

from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import (
    NotebookOrigin,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.domain.errors import (
    AutoNotebookLimitError,
    FeatureDisabledError,
    InvalidOptionsError,
    NotebookNotFoundError,
    SubjectNotFoundError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_auto import AutoServices, build_auto
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.contracts.academic import LessonRef, ScheduleQueries
from app.shared.contracts.links import LinksApi
from app.shared.ids import new_id
from tests.fakes.ai.contracts import make_lesson
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.auto.conftest import (
    open_subject,
    student_file,
    teacher_file,
)

import pytest


async def _sources(uow_factory: UowFactory, notebook_id: UUID) -> list[Source]:
    async with uow_factory() as uow:
        return await uow.sources.list_for_notebook(notebook_id)


async def test_the_subject_notebook_is_created_and_filled_from_teacher_materials(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
    kicker: FakeTaskKicker,
) -> None:
    """NB-AUTO: opening it the first time creates it with the lesson materials."""
    link = teacher_file(world, physics)

    notebook = await open_subject(auto, student, physics)

    assert notebook.origin is NotebookOrigin.SUBJECT_AUTO
    assert notebook.title == "Physics" and not notebook.title_auto
    assert notebook.subject_id == physics.subject_id and notebook.lesson_id is None
    assert notebook.auto_settings is not None
    assert notebook.auto_settings.include_classmates is False
    assert notebook.auto_synced_at is not None
    assert notebook.space_key is not None
    assert notebook.space_key.startswith(f"subject:{physics.subject_id}:2026-09-01")
    assert notebook.source_count == 1
    [source] = await _sources(uow_factory, notebook.id)
    assert source.kind is SourceKind.LESSON_RESOURCE
    assert source.ref_key == f"lesson:{link}"
    assert source.status is SourceStatus.PENDING
    assert source.origin is not None and source.origin["subject"] == "Physics"
    assert ("notebooks.process_source", {"source_id": str(source.id)}) in kicker.calls


async def test_opening_again_returns_the_same_notebook(
    auto: AutoServices,
    world: World,
    student: Actor,
    physics: LessonRef,
    clock: FixedClock,
) -> None:
    """NB-AUTO: get-or-create is idempotent and makes it the last opened."""
    teacher_file(world, physics)
    first = await open_subject(auto, student, physics)
    clock.advance(minutes=1)

    again = await open_subject(auto, student, physics)

    assert again.id == first.id
    assert again.last_opened_at == clock.now()
    assert again.source_count == 1


async def test_a_lookup_does_not_create_or_touch_anything(
    auto: AutoServices,
    world: World,
    student: Actor,
    physics: LessonRef,
    clock: FixedClock,
) -> None:
    """NB-AUTO: the card on the subject page only looks; a 404 means "not yet"."""
    with pytest.raises(NotebookNotFoundError):
        await auto.open_auto_notebook.execute(
            student, NotebookOrigin.SUBJECT_AUTO, physics.subject_id, create=False
        )
    created = await open_subject(auto, student, physics)
    opened_at = created.last_opened_at
    clock.advance(hours=1)

    found = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, physics.subject_id, create=False
    )

    assert found.id == created.id and found.last_opened_at == opened_at


async def test_each_student_has_their_own_notebook_of_the_subject(
    auto: AutoServices,
    world: World,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: the notebook is private; two students never share a row."""
    world.schedule.attend(other_student.user_id, physics)

    mine = await open_subject(auto, student, physics)
    theirs = await open_subject(auto, other_student, physics)

    assert mine.id != theirs.id and theirs.owner_id == other_student.user_id


async def test_a_known_subject_without_lessons_yet_gets_an_empty_notebook(
    auto: AutoServices, world: World, student: Actor, other_student: Actor
) -> None:
    """A fresh student whose timetable has not synced yet still gets the notebook.

    It is empty: only the student's own lessons ever feed it, so nothing of other
    students leaks in; the sync job fills it once the lessons arrive.
    """
    foreign = world.schedule.attend(other_student.user_id, make_lesson(subject="Art"))
    teacher_file(world, foreign)

    notebook = await open_subject(auto, student, foreign)

    assert notebook.owner_id == student.user_id
    assert notebook.subject_id == foreign.subject_id and notebook.title == "Art"
    assert notebook.source_count == 0


async def test_a_subject_named_only_in_the_catalogue_gets_a_notebook(
    auto: AutoServices, world: World, student: Actor
) -> None:
    """No lessons at all yet: the title comes from the subject itself."""
    subject_id = new_id()
    world.schedule.name_subject(subject_id, "Chemistry")

    notebook = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, subject_id
    )

    assert notebook.title == "Chemistry" and notebook.source_count == 0
    again = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, subject_id
    )
    assert again.id == notebook.id


async def test_an_unknown_subject_is_refused_clearly(
    auto: AutoServices, student: Actor
) -> None:
    """A subject id the school does not know answers "subject not found"."""
    with pytest.raises(SubjectNotFoundError):
        await auto.open_auto_notebook.execute(
            student, NotebookOrigin.SUBJECT_AUTO, new_id()
        )


async def test_only_lessons_of_this_term_feed_the_subject_notebook(
    auto: AutoServices, world: World, student: Actor, physics: LessonRef
) -> None:
    """NB-AUTO: materials of an earlier term do not come into this term's notebook."""
    teacher_file(world, physics, "This term")
    last_term = world.schedule.attend(
        student.user_id,
        make_lesson(
            subject="Physics", subject_id=physics.subject_id, day=dt.date(2026, 3, 2)
        ),
    )
    teacher_file(world, last_term, "Last term")

    notebook = await open_subject(auto, student, physics)

    assert notebook.source_count == 1


async def test_the_lesson_notebook_holds_that_lessons_materials(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: a lesson notebook is titled with the subject and the date."""
    link = teacher_file(world, physics)
    other_day = world.schedule.attend(
        student.user_id,
        make_lesson(
            subject="Physics", subject_id=physics.subject_id, day=dt.date(2026, 10, 9)
        ),
    )
    teacher_file(world, other_day, "Next lesson")

    notebook = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.LESSON_AUTO, physics.id
    )

    assert notebook.origin is NotebookOrigin.LESSON_AUTO
    assert notebook.title == "Physics · 07.10.2026"
    assert (
        notebook.lesson_id == physics.id and notebook.subject_id == physics.subject_id
    )
    assert notebook.space_key == f"lesson:{physics.id}"
    assert [s.ref_key for s in await _sources(uow_factory, notebook.id)] == [
        f"lesson:{link}"
    ]


async def test_a_lesson_the_student_does_not_attend_is_not_found(
    auto: AutoServices, world: World, student: Actor, other_student: Actor
) -> None:
    """NB-AUTO: another group's lesson answers 404, never its materials."""
    foreign = world.schedule.attend(other_student.user_id, make_lesson())
    teacher_file(world, foreign)

    with pytest.raises(NotebookNotFoundError):
        await auto.open_auto_notebook.execute(
            student, NotebookOrigin.LESSON_AUTO, foreign.id
        )


async def test_a_manual_origin_is_refused(
    auto: AutoServices, student: Actor, physics: LessonRef
) -> None:
    """NB-AUTO: only subject and lesson notebooks are get-or-create."""
    with pytest.raises(InvalidOptionsError):
        await auto.open_auto_notebook.execute(
            student, NotebookOrigin.MANUAL, physics.subject_id
        )


async def test_the_number_of_auto_notebooks_is_limited(
    auto: AutoServices,
    world: World,
    student: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NB-AUTO: a student cannot fill the database with lesson notebooks."""
    monkeypatch.setattr(
        "app.modules.notebooks.application.open_auto_notebook.MAX_AUTO_NOTEBOOKS", 2
    )
    lessons = [
        world.schedule.attend(
            student.user_id, make_lesson(day=dt.date(2026, 10, 1) + timedelta(days=n))
        )
        for n in range(3)
    ]
    for lesson in lessons[:2]:
        await auto.open_auto_notebook.execute(
            student, NotebookOrigin.LESSON_AUTO, lesson.id
        )

    with pytest.raises(AutoNotebookLimitError):
        await auto.open_auto_notebook.execute(
            student, NotebookOrigin.LESSON_AUTO, lessons[2].id
        )


async def test_an_old_sync_is_repeated_in_the_background_when_it_is_opened(
    auto: AutoServices,
    world: World,
    student: Actor,
    physics: LessonRef,
    clock: FixedClock,
    kicker: FakeTaskKicker,
) -> None:
    """NB-AUTO: opening after ten minutes asks the job to sync again."""
    created = await open_subject(auto, student, physics)
    kicker.calls.clear()
    clock.advance(minutes=5)
    await open_subject(auto, student, physics)
    assert kicker.calls == []

    clock.advance(minutes=6)
    await open_subject(auto, student, physics)

    assert kicker.calls == [
        ("notebooks.sync_auto_notebook", {"notebook_id": str(created.id)})
    ]


async def test_without_the_academic_contracts_the_feature_is_off(
    core: NotebooksCore,
    sources: SourcesServices,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: a process without classwork and terms answers "feature disabled"."""
    off = build_auto(
        core,
        readers=sources.readers,
        links=cast(LinksApi, world.links),
        schedule=cast(ScheduleQueries, world.schedule),
        classwork=None,
        terms=None,
    )

    with pytest.raises(FeatureDisabledError):
        await open_subject(off, student, physics)


async def test_a_classmates_file_is_not_in_a_new_notebook(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: "Include classmates' files" starts off."""
    world.schedule.attend(other_student.user_id, physics)
    student_file(world, physics, other_student)

    notebook = await open_subject(auto, student, physics)

    assert notebook.source_count == 0
