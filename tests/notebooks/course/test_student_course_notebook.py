"""LMS-NB: a student's course notebook is created on enrollment, synced, backfilled."""

from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import NotebookOrigin, SourceKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_source
from tests.fakes.notebooks.lms import FakeCourse
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker

import pytest


async def _student_notebook(
    uow_factory: UowFactory, user_id: UUID, course_id: UUID
) -> Notebook | None:
    async with uow_factory() as uow:
        return await uow.notebooks.find_course_student(user_id, course_id)


async def _sources(uow_factory: UowFactory, notebook_id: UUID) -> list[Source]:
    async with uow_factory() as uow:
        return await uow.sources.list_for_notebook(notebook_id)


def _by_ref_key(sources: list[Source]) -> dict[str, Source]:
    """Sources that have a reference key (the course materials), by that key."""
    return {s.ref_key: s for s in sources if s.ref_key is not None}


@pytest.fixture
def enrolled_course(world: World, student: Actor) -> FakeCourse:
    """A published course with one step; `student` is enrolled."""
    course = world.lms.add_course("Biology 10", enrolled=(student.user_id,))
    world.lms.add_step(course, "Cells")
    return course


async def test_enrollment_provisions_one_course_notebook(
    services: NotebooksServices,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
    student: Actor,
    enrolled_course: FakeCourse,
) -> None:
    """The job creates the student's course notebook with the steps as sources."""
    notebook = await services.provision_course_notebook.execute(
        student.user_id, enrolled_course.id
    )
    assert notebook is not None
    assert notebook.origin is NotebookOrigin.COURSE_STUDENT
    assert notebook.is_course_student
    assert notebook.course_id == enrolled_course.id
    assert notebook.owner_id == student.user_id

    found = await _student_notebook(uow_factory, student.user_id, enrolled_course.id)
    assert found is not None and found.id == notebook.id

    step_id, step = next(iter(enrolled_course.steps.items()))
    refs = _by_ref_key(await _sources(uow_factory, notebook.id))
    assert set(refs) == {f"lms:{step_id}"}
    assert refs[f"lms:{step_id}"].kind is SourceKind.LMS_STEP
    assert refs[f"lms:{step_id}"].ref["revision_id"] == "rev-1"
    # The notebook is the course, so the source title is the step title alone.
    assert refs[f"lms:{step_id}"].title == step.title
    assert refs[f"lms:{step_id}"].origin["course_title"] == enrolled_course.title
    assert "notebooks.process_source" in kicker.names()


async def test_provision_is_idempotent(
    services: NotebooksServices,
    uow_factory: UowFactory,
    student: Actor,
    enrolled_course: FakeCourse,
) -> None:
    """A second run (opening the page) returns the same notebook, adds no sources."""
    first = await services.provision_course_notebook.execute(
        student.user_id, enrolled_course.id
    )
    assert first is not None
    count = len(await _sources(uow_factory, first.id))

    again = await services.provision_course_notebook.execute(
        student.user_id, enrolled_course.id, touch=True
    )
    assert again is not None and again.id == first.id
    assert len(await _sources(uow_factory, first.id)) == count

    async with uow_factory() as uow:
        live = [
            n
            for n in await uow.notebooks.list_for_owner(
                student.user_id, query=None, after=None, limit=50
            )
            if n.origin is NotebookOrigin.COURSE_STUDENT
        ]
    assert [n.id for n in live] == [first.id]


async def test_not_enrolled_gets_no_notebook(
    services: NotebooksServices,
    uow_factory: UowFactory,
    other_student: Actor,
    enrolled_course: FakeCourse,
) -> None:
    """A student who is not enrolled gets nothing and no notebook row."""
    result = await services.provision_course_notebook.execute(
        other_student.user_id, enrolled_course.id
    )
    assert result is None
    assert (
        await _student_notebook(uow_factory, other_student.user_id, enrolled_course.id)
        is None
    )


async def test_publish_syncs_new_and_revised_materials(
    services: NotebooksServices,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
    world: World,
    student: Actor,
    enrolled_course: FakeCourse,
) -> None:
    """A publish fans out one sync; it adds the new step and refreshes the revised."""
    notebook = await services.provision_course_notebook.execute(
        student.user_id, enrolled_course.id
    )
    assert notebook is not None
    step = next(iter(enrolled_course.steps.values()))
    step.revision = 2
    new_step = world.lms.add_step(enrolled_course, "Organs")

    kicker.calls.clear()
    fanned = await services.sync_course_notebooks.execute(enrolled_course.id)
    assert fanned == 1
    assert kicker.calls == [
        ("notebooks.sync_course_notebook", {"notebook_id": str(notebook.id)})
    ]

    result = await services.sync_course_notebook.execute(notebook.id)
    assert (result.added, result.refreshed, result.removed) == (1, 1, 0)
    refs = _by_ref_key(await _sources(uow_factory, notebook.id))
    assert refs[f"lms:{step.id}"].ref["revision_id"] == "rev-2"
    assert refs[f"lms:{new_step.id}"].ref["revision_id"] == "rev-1"


async def test_sync_is_idempotent_and_drops_removed_steps(
    services: NotebooksServices,
    uow_factory: UowFactory,
    student: Actor,
    enrolled_course: FakeCourse,
) -> None:
    """A second sync changes nothing; a step removed from the course is dropped."""
    notebook = await services.provision_course_notebook.execute(
        student.user_id, enrolled_course.id
    )
    assert notebook is not None
    again = await services.sync_course_notebook.execute(notebook.id)
    assert (again.added, again.refreshed, again.removed) == (0, 0, 0)

    enrolled_course.steps.clear()
    gone = await services.sync_course_notebook.execute(notebook.id)
    assert gone.removed == 1
    assert _by_ref_key(await _sources(uow_factory, notebook.id)) == {}


async def test_student_own_sources_survive_sync(
    services: NotebooksServices,
    uow_factory: UowFactory,
    student: Actor,
    enrolled_course: FakeCourse,
) -> None:
    """The sync owns only the materials; the student's own source is kept."""
    notebook = await services.provision_course_notebook.execute(
        student.user_id, enrolled_course.id
    )
    assert notebook is not None
    own = await make_source(
        uow_factory, notebook, title="My notes", texts=("Cells divide by mitosis.",)
    )
    enrolled_course.steps.clear()
    await services.sync_course_notebook.execute(notebook.id)
    assert own.id in {s.id for s in await _sources(uow_factory, notebook.id)}


async def test_backfill_provisions_existing_enrollments(
    services: NotebooksServices,
    uow_factory: UowFactory,
    student: Actor,
    enrolled_course: FakeCourse,
) -> None:
    """The backfill creates the notebook of every enrollment already there, once."""
    result = await services.backfill_course_notebooks.execute(inline=True)
    assert (result.enrollments, result.created) == (1, 1)
    assert await _student_notebook(uow_factory, student.user_id, enrolled_course.id)

    again = await services.backfill_course_notebooks.execute(inline=True)
    assert (again.enrollments, again.created) == (1, 0)
