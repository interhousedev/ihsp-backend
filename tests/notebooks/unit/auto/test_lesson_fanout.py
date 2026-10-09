"""NB-AUTO: a changed lesson starts the sync of the notebooks that feed on it."""

import datetime as dt
from datetime import timedelta

from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_auto import AutoServices
from app.shared.actor import Actor
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id
from tests.fakes.ai.contracts import make_lesson
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.auto.conftest import open_subject

SYNC = "notebooks.sync_auto_notebook"


async def test_every_notebook_of_the_subject_and_of_the_lesson_is_synced(
    auto: AutoServices,
    world: World,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
    kicker: FakeTaskKicker,
) -> None:
    """NB-AUTO: links says "this lesson changed"; each affected notebook is kicked."""
    world.schedule.attend(other_student.user_id, physics)
    mine = await open_subject(auto, student, physics)
    theirs = await open_subject(auto, other_student, physics)
    lesson_book = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.LESSON_AUTO, physics.id
    )
    elsewhere = world.schedule.attend(student.user_id, make_lesson(subject="Art"))
    await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, elsewhere.subject_id
    )
    kicker.calls.clear()

    count = await auto.sync_lesson_notebooks.execute(physics.id)

    kicked = {kwargs["notebook_id"] for name, kwargs in kicker.calls if name == SYNC}
    assert count == 3
    assert kicked == {str(mine.id), str(theirs.id), str(lesson_book.id)}


async def test_an_unknown_lesson_kicks_nothing(
    auto: AutoServices, kicker: FakeTaskKicker
) -> None:
    """NB-AUTO: a lesson that is gone (or never was) is not an error."""
    assert await auto.sync_lesson_notebooks.execute(new_id()) == 0
    assert kicker.calls == []


async def test_the_sweep_picks_notebooks_opened_lately_and_not_synced_for_an_hour(
    auto: AutoServices,
    world: World,
    student: Actor,
    physics: LessonRef,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    uow_factory: UowFactory,
) -> None:
    """NB-AUTO: the safety net skips fresh syncs and notebooks nobody has opened."""
    fresh = await open_subject(auto, student, physics)
    stale_lesson = world.schedule.attend(
        student.user_id, make_lesson(subject="Art", day=dt.date(2026, 10, 5))
    )
    stale = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, stale_lesson.subject_id
    )
    kicker.calls.clear()
    assert await auto.sweep_auto_notebooks.execute() == 0

    clock.advance(minutes=61)
    async with uow_factory() as uow:  # `fresh` was synced again a minute ago
        again = await uow.notebooks.get(fresh.id)
        assert again is not None
        again.auto_synced_at = clock.now() - timedelta(minutes=1)
        await uow.notebooks.save(again)
        await uow.commit()
    swept = await auto.sweep_auto_notebooks.execute()

    assert swept == 1
    assert kicker.calls == [(SYNC, {"notebook_id": str(stale.id)})]

    clock.advance(days=31)  # nobody opened them for a month
    kicker.calls.clear()
    assert await auto.sweep_auto_notebooks.execute() == 0
