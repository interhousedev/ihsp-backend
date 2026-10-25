"""FILE-6, NB-3, NB-8: sources whose file is gone, and upstream changes."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import (
    GuideStatus,
    SourceFailure,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.domain.source_input import (
    FileInput,
    FlashcardSetInput,
    LessonResourceInput,
    LmsStepInput,
    TextInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.fakes.ai.contracts import make_file, make_lesson
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.links import make_resource
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.sources.support import (
    add_one,
    add_ready,
    passages_of,
    stored,
    stored_notebook,
)

import pytest

TEXT = "Photosynthesis turns light into chemical energy in plants."


# - - - FILE-6: the file is gone - - -


async def test_a_deleted_file_makes_its_source_unavailable_and_drops_the_text(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """FILE-6, NB-3: the row and title stay, the passages and the counters go."""
    ref = world.files.add_text(make_file(student.user_id, name="Biology.pdf"), TEXT)
    file_source = await add_ready(
        sources, uow_factory, student, notebook, FileInput(file_id=ref.id)
    )
    kept = await add_ready(
        sources, uow_factory, student, notebook, TextInput(title="Notes", text=TEXT)
    )
    world.files.delete(ref.id)

    assert await sources.sweep_sources.execute() == 1

    gone = await stored(uow_factory, file_source.id)
    assert gone.status is SourceStatus.UNAVAILABLE
    assert gone.failure is SourceFailure.DELETED
    assert gone.title == "Biology.pdf"
    assert (gone.passage_count, gone.char_count, gone.word_count) == (0, 0, 0)
    assert (gone.content_hash, gone.guide, gone.guide_status) == (
        None,
        None,
        GuideStatus.NONE,
    )
    assert await passages_of(uow_factory, file_source.id) == []
    assert (await stored(uow_factory, kept.id)).status is SourceStatus.READY
    saved = await stored_notebook(uow_factory, notebook.id)
    assert (saved.source_count, saved.char_count) == (2, kept.char_count)


async def test_a_second_sweep_has_nothing_left_to_do(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """FILE-6: unavailable sources are not touched again."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    await add_ready(sources, uow_factory, student, notebook, FileInput(file_id=ref.id))
    world.files.delete(ref.id)

    assert await sources.sweep_sources.execute() == 1
    assert await sources.sweep_sources.execute() == 0


async def test_a_file_that_lost_its_text_makes_its_source_unavailable(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """FILE-6: a file without extracted text cannot back a source."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    source = await add_ready(
        sources, uow_factory, student, notebook, FileInput(file_id=ref.id)
    )
    world.files.drop_text(ref.id)

    assert await sources.sweep_sources.execute() == 1

    assert (await stored(uow_factory, source.id)).status is SourceStatus.UNAVAILABLE


async def test_the_file_of_a_lesson_material_is_checked_but_a_link_is_not(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
) -> None:
    """FILE-6: only file-backed lesson materials depend on a stored file."""
    lesson = world.schedule.attend(student.user_id, make_lesson())
    ref = world.files.add_text(make_file(other_student.user_id), TEXT)
    file_resource = world.links.add(make_resource(lesson.id, file_id=ref.id))
    link_resource = world.links.add(make_resource(lesson.id, title="Article"))
    world.fetcher.add_page(link_resource.short_url, TEXT)
    from_file = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LessonResourceInput(lesson_id=lesson.id, link_id=file_resource.link_id),
    )
    from_link = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LessonResourceInput(lesson_id=lesson.id, link_id=link_resource.link_id),
    )
    world.files.delete(ref.id)

    assert await sources.sweep_sources.execute() == 1

    assert (await stored(uow_factory, from_file.id)).status is SourceStatus.UNAVAILABLE
    assert (await stored(uow_factory, from_link.id)).status is SourceStatus.READY


async def test_intact_files_and_unfinished_sources_are_left_alone(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """FILE-6: a ready file stays ready; a source not read yet is not touched."""
    ref = world.files.add_text(make_file(student.user_id, name="A.pdf"), TEXT)
    ready = await add_ready(
        sources, uow_factory, student, notebook, FileInput(file_id=ref.id)
    )
    waiting_ref = world.files.add_text(make_file(student.user_id, name="B.pdf"), TEXT)
    waiting = await add_one(
        sources, student, notebook, FileInput(file_id=waiting_ref.id)
    )
    world.files.delete(waiting_ref.id)

    assert await sources.sweep_sources.execute() == 0

    assert (await stored(uow_factory, ready.id)).status is SourceStatus.READY
    assert (await stored(uow_factory, waiting.id)).status is SourceStatus.PENDING


async def test_the_summary_goes_when_the_only_selected_source_is_unavailable(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """FILE-6, NB-4: nothing usable is selected, so there is nothing to summarise."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    await add_ready(sources, uow_factory, student, notebook, FileInput(file_id=ref.id))
    assert (
        await stored_notebook(uow_factory, notebook.id)
    ).summary_status is SummaryStatus.STALE
    world.files.delete(ref.id)

    await sources.sweep_sources.execute()

    saved = await stored_notebook(uow_factory, notebook.id)
    assert (saved.summary_status, saved.summary_due_at) == (SummaryStatus.NONE, None)


async def test_the_sweep_covers_every_notebook_of_every_student(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """FILE-6: one run, several owners; each notebook is recounted."""
    mine = world.files.add_text(make_file(student.user_id), TEXT)
    theirs = world.files.add_text(make_file(other_student.user_id), TEXT)
    await add_ready(sources, uow_factory, student, notebook, FileInput(file_id=mine.id))
    await add_ready(
        sources,
        uow_factory,
        other_student,
        their_notebook,
        FileInput(file_id=theirs.id),
    )
    world.files.delete(mine.id)
    world.files.delete(theirs.id)

    assert await sources.sweep_sources.execute() == 2

    for nb in (notebook, their_notebook):
        assert (await stored_notebook(uow_factory, nb.id)).char_count == 0


# - - - FILE-6: the same check when a source is opened - - -


async def test_opening_a_source_of_a_deleted_file_marks_it_unavailable_once(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    clock: FixedClock,
) -> None:
    """FILE-6: no waiting for the daily job; repeated opens change nothing more."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    source = await add_ready(
        sources, uow_factory, student, notebook, FileInput(file_id=ref.id)
    )
    world.files.delete(ref.id)

    opened = await sources.get_source.execute(student, notebook.id, source.id)

    assert opened.status is SourceStatus.UNAVAILABLE
    assert opened.failure is SourceFailure.DELETED
    assert await passages_of(uow_factory, source.id) == []
    assert (await stored(uow_factory, source.id)).status is SourceStatus.UNAVAILABLE
    first = await stored_notebook(uow_factory, notebook.id)
    assert first.char_count == 0

    clock.advance(hours=1)
    again = await sources.get_source.execute(student, notebook.id, source.id)

    assert again.status is SourceStatus.UNAVAILABLE
    assert (
        await stored_notebook(uow_factory, notebook.id)
    ).updated_at == first.updated_at


async def test_opening_a_source_with_a_live_file_changes_nothing(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """FILE-6: a ready file and other kinds come back as they are."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    from_file = await add_ready(
        sources, uow_factory, student, notebook, FileInput(file_id=ref.id)
    )
    pasted = await add_ready(
        sources, uow_factory, student, notebook, TextInput(title="Notes", text=TEXT)
    )

    for source in (from_file, pasted):
        opened = await sources.get_source.execute(student, notebook.id, source.id)
        assert opened.status is SourceStatus.READY
        assert opened.passage_count == source.passage_count


async def test_another_student_cannot_open_the_source(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
) -> None:
    """NB-15: a 404, as for a source that does not exist."""
    source = await add_ready(
        sources, uow_factory, student, notebook, TextInput(title="Notes", text=TEXT)
    )

    with pytest.raises(NotebookNotFoundError):
        await sources.get_source.execute(other_student, notebook.id, source.id)


# - - - NB-8: upstream changes - - -


async def test_an_edited_flashcard_set_makes_its_source_outdated_but_usable(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-8: a stale source keeps its text and counts in the notebook."""
    found = world.flashcards.add_set(student.user_id)
    source = await add_ready(
        sources, uow_factory, student, notebook, FlashcardSetInput(set_id=found["id"])
    )
    chars = (await stored_notebook(uow_factory, notebook.id)).char_count

    assert await sources.sweep_sources.execute() == 0
    world.flashcards.edit(found["id"], 0, "Something else")
    assert await sources.sweep_sources.execute() == 1

    outdated = await stored(uow_factory, source.id)
    assert outdated.status is SourceStatus.STALE
    assert outdated.usable
    assert outdated.passage_count == source.passage_count
    assert (await stored_notebook(uow_factory, notebook.id)).char_count == chars
    assert await sources.sweep_sources.execute() == 0


async def test_a_vanished_upstream_object_is_not_called_outdated(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-8: a deleted set or a lost enrolment cannot be synced, so nothing changes."""
    found = world.flashcards.add_set(student.user_id)
    cards = await add_ready(
        sources, uow_factory, student, notebook, FlashcardSetInput(set_id=found["id"])
    )
    course = world.lms.add_course(enrolled=(student.user_id,))
    step = world.lms.add_step(course)
    lms = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LmsStepInput(course_id=course.id, step_id=step.id),
    )
    del world.flashcards.sets[found["id"]]
    course.enrolled.clear()

    assert await sources.sweep_sources.execute() == 0

    assert (await stored(uow_factory, cards.id)).status is SourceStatus.READY
    assert (await stored(uow_factory, lms.id)).status is SourceStatus.READY


async def test_sources_of_unversioned_kinds_are_never_outdated(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-8: pasted text has no upstream to compare with."""
    pasted = await add_ready(
        sources, uow_factory, student, notebook, TextInput(title="Notes", text=TEXT)
    )

    assert await sources.sweep_sources.execute() == 0

    assert (await stored(uow_factory, pasted.id)).status is SourceStatus.READY
