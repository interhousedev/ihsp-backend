"""T6.3: subject notebooks hold homework, library books and materials; provisioning."""

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import NotebookOrigin, SourceKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_auto import AutoServices, build_auto
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import (
    ClassworkQueries,
    LessonRef,
    ScheduleQueries,
)
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.library import LessonItemRefView, LibraryQueries
from app.shared.contracts.links import LinksApi
from app.shared.ids import new_id
from tests.fakes.ai.contracts import make_file, make_lesson
from tests.fakes.notebooks.library import FakeBook
from tests.fakes.notebooks.links import make_resource
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.auto.conftest import PAGE, open_subject, teacher_file

import pytest


class FakeBookLinks:
    """LibraryQueries.lesson_item_refs: the books lessons follow."""

    def __init__(self) -> None:
        """Start with no links."""
        self.items: dict[UUID, list[LessonItemRefView]] = {}

    def link(
        self,
        lesson: LessonRef,
        book: FakeBook,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> None:
        """The lesson follows the book (or a page range)."""
        self.items.setdefault(lesson.id, []).append(
            LessonItemRefView(book.id, book.title, "", page_from, page_to)
        )

    async def lesson_item_refs(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[LessonItemRefView]]:
        """The links of the lessons."""
        return {i: self.items[i] for i in lesson_ids if i in self.items}


class FakeRoster:
    """IdentityDirectory.user_ids_with_roles for the backfill."""

    def __init__(self, *ids: UUID) -> None:
        """The students."""
        self.ids = list(ids)

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Every id (all are students)."""
        return list(self.ids)


@pytest.fixture
def book_links() -> FakeBookLinks:
    """The books that lessons follow."""
    return FakeBookLinks()


@pytest.fixture
def roster(student: Actor, other_student: Actor) -> FakeRoster:
    """Two students."""
    return FakeRoster(student.user_id, other_student.user_id)


@pytest.fixture
def auto(  # type: ignore[override]
    core: NotebooksCore,
    sources: SourcesServices,
    world: World,
    book_links: FakeBookLinks,
    roster: FakeRoster,
) -> AutoServices:
    """The auto notebook services with the library links and a student roster."""
    return build_auto(
        core,
        readers=sources.readers,
        links=cast(LinksApi, world.links),
        schedule=cast(ScheduleQueries, world.schedule),
        classwork=cast(ClassworkQueries, world.classwork),
        terms=world.terms,
        library=cast(LibraryQueries, book_links),
        identity=cast(IdentityDirectory, roster),
    )


async def _sources(uow_factory: UowFactory, notebook_id: UUID) -> list[Source]:
    async with uow_factory() as uow:
        return await uow.sources.list_for_notebook(notebook_id)


def _homework(world: World, lesson: LessonRef, title: str = "Task") -> str:
    ref = world.files.add_text(make_file(lesson.id, name=f"{title}.pdf"), PAGE)
    resource = world.links.add(
        make_resource(lesson.id, title=title, file_id=ref.id, role="homework")
    )
    return str(resource.link_id)


async def test_homework_files_of_the_lessons_are_in_the_notebook(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """T6.3: homework attachments are sources next to the materials."""
    material = teacher_file(world, physics, "Waves")
    homework = _homework(world, physics)

    notebook = await open_subject(auto, student, physics)

    keys = {s.ref_key for s in await _sources(uow_factory, notebook.id)}
    assert keys == {f"lesson:{material}", f"lesson:{homework}"}


async def test_a_book_the_lesson_follows_comes_in_once_by_reference(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
    book_links: FakeBookLinks,
    kicker: FakeTaskKicker,
) -> None:
    """T6.3: a linked book is a library source, added once, read once."""
    book = world.library.add_book("Physics 10")
    book_links.link(physics, book)
    notebook = await open_subject(auto, student, physics)
    reads = world.library.calls.count("read_text")

    again = await auto.sync_auto_notebook.execute(notebook.id)

    stored = await _sources(uow_factory, notebook.id)
    assert [s.kind for s in stored] == [SourceKind.LIBRARY_ITEM]
    assert stored[0].ref["item_id"] == str(book.id)
    assert (again.added, again.removed) == (0, 0)
    assert world.library.calls.count("read_text") == reads  # no second read


async def test_a_new_book_link_is_added_and_a_removed_one_is_dropped(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
    book_links: FakeBookLinks,
) -> None:
    """T6.3: the sync follows the library links both ways."""
    notebook = await open_subject(auto, student, physics)
    assert await _sources(uow_factory, notebook.id) == []
    book = world.library.add_book("Optics")
    book_links.link(physics, book)

    added = await auto.sync_auto_notebook.execute(notebook.id)
    book_links.items.clear()
    removed = await auto.sync_auto_notebook.execute(notebook.id)

    assert (added.added, removed.removed) == (1, 1)
    assert await _sources(uow_factory, notebook.id) == []


async def test_an_excluded_book_stays_out(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
    book_links: FakeBookLinks,
) -> None:
    """T6.3: an excluded book stays out on every sync."""
    book = world.library.add_book("Physics 10")
    book_links.link(physics, book)
    notebook = await open_subject(auto, student, physics)
    [auto_book] = await _sources(uow_factory, notebook.id)

    await auto.update_auto_settings.execute(
        student, notebook.id, {"exclude_source_ids": [auto_book.id]}
    )
    await auto.sync_auto_notebook.execute(notebook.id)

    assert await _sources(uow_factory, notebook.id) == []


async def test_an_excluded_material_is_not_added_back(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """T6.3: the sync job respects what the student removed."""
    keep = teacher_file(world, physics, "Keep")
    drop = teacher_file(world, physics, "Drop")
    notebook = await open_subject(auto, student, physics)
    gone = next(
        s
        for s in await _sources(uow_factory, notebook.id)
        if s.ref_key == f"lesson:{drop}"
    )
    await auto.update_auto_settings.execute(
        student, notebook.id, {"exclude_source_ids": [gone.id]}
    )
    late = teacher_file(world, physics, "Late")

    result = await auto.sync_auto_notebook.execute(notebook.id)

    keys = [s.ref_key for s in await _sources(uow_factory, notebook.id)]
    assert sorted(k or "" for k in keys) == sorted([f"lesson:{keep}", f"lesson:{late}"])
    assert result.added == 1  # only the late one
    assert len(keys) == len(set(keys))


# - - - Provisioning - - -


async def _notebooks(uow_factory: UowFactory, user_id: UUID) -> int:
    async with uow_factory() as uow:
        return await uow.notebooks.count_live_auto(user_id)


async def test_provisioning_creates_and_fills_a_notebook_per_subject(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """T6.3: every subject of the term gets a filled notebook."""
    biology = world.schedule.attend(
        student.user_id, make_lesson(subject="Biology", day=physics.date)
    )
    teacher_file(world, physics, "Waves")

    created = await auto.provision_student_notebooks.execute(student.user_id)

    assert created == 2
    assert await _notebooks(uow_factory, student.user_id) == 2
    notebook = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, physics.subject_id, create=False
    )
    assert len(await _sources(uow_factory, notebook.id)) == 1
    assert biology.subject_id != physics.subject_id


async def test_provisioning_twice_changes_nothing(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """T6.3: idempotent: the second run creates nothing and keeps the sources."""
    teacher_file(world, physics)
    await auto.provision_student_notebooks.execute(student.user_id)
    notebook = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, physics.subject_id, create=False
    )
    before = [s.id for s in await _sources(uow_factory, notebook.id)]

    created = await auto.provision_student_notebooks.execute(student.user_id)

    assert created == 0
    assert await _notebooks(uow_factory, student.user_id) == 1
    assert [s.id for s in await _sources(uow_factory, notebook.id)] == before


async def test_a_user_who_is_not_a_student_gets_nothing(
    auto: AutoServices, uow_factory: UowFactory, world: World, physics: LessonRef
) -> None:
    """T6.3: without lessons there is nothing to create."""
    nobody = new_id()

    assert await auto.provision_student_notebooks.execute(nobody) == 0
    assert await _notebooks(uow_factory, nobody) == 0


async def test_the_backfill_provisions_every_student_in_place(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
) -> None:
    """T6.3: the one-off command covers the students that already exist."""
    world.schedule.attend(other_student.user_id, physics)

    first = await auto.backfill_subject_notebooks.execute(inline=True)
    second = await auto.backfill_subject_notebooks.execute(inline=True)

    assert (first.students, first.created) == (2, 2)
    assert second.created == 0
    assert await _notebooks(uow_factory, student.user_id) == 1
    assert await _notebooks(uow_factory, other_student.user_id) == 1


async def test_the_daily_backfill_only_queues_a_task_per_student(
    auto: AutoServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
    kicker: FakeTaskKicker,
) -> None:
    """T6.3: the periodic run never holds a worker; it queues the provisioning."""
    kicker.calls.clear()

    result = await auto.backfill_subject_notebooks.execute()

    assert result.students == 2
    assert sorted(str(c[1]["user_id"]) for c in kicker.calls) == sorted(
        [str(student.user_id), str(other_student.user_id)]
    )
    assert {c[0] for c in kicker.calls} == {"notebooks.provision_student_notebooks"}
    assert await _notebooks(uow_factory, student.user_id) == 0
