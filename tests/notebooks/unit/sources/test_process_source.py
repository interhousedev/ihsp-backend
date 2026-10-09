"""NB-3, NB-4: `notebooks.process_source` reads, chunks and stores a source."""

from datetime import timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, SourceGuide
from app.modules.notebooks.domain.enums import (
    GuideStatus,
    SourceFailure,
    SourceKind,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.domain.source_input import (
    ChatInput,
    FileInput,
    FlashcardSetInput,
    LmsStepInput,
    TextInput,
    UrlInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.contracts.files import FullText
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.contracts import make_file
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.conftest import Build
from tests.notebooks.unit.sources.support import (
    GUIDE_TASK,
    add_one,
    add_ready,
    passages_of,
    stored,
    stored_notebook,
)

import pytest

URL = "http://example.com/a"
TEXT = "Photosynthesis turns light into chemical energy in plants."


async def _set_guide(uow_factory: UowFactory, source_id: UUID) -> None:
    async with uow_factory() as uow:
        source = await uow.sources.get_for_update(source_id)
        assert source is not None
        source.guide = SourceGuide(summary="Cards about cells.")
        source.guide_status = GuideStatus.READY
        await uow.sources.save(source)
        await uow.commit()


# - - - The happy path - - -


async def test_a_ready_source_has_counters_and_makes_the_summary_due(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    clock: FixedClock,
) -> None:
    """NB-3, NB-4: counters, the sync time and a summary due in 20 seconds."""
    item = TextInput(title="Notes", text=f"{TEXT}\n\nIt happens in the chloroplasts.")

    ready = await add_ready(sources, uow_factory, student, notebook, item)

    assert ready.status is SourceStatus.READY
    assert ready.failure is None
    assert ready.passage_count >= 1
    assert ready.char_count == len(ready.body_md or "")
    assert ready.word_count == 13
    assert ready.token_estimate > 0
    assert ready.content_hash is not None
    assert ready.text_synced_at == clock.now()
    saved = await stored_notebook(uow_factory, notebook.id)
    assert saved.char_count == ready.char_count
    assert saved.summary_status is SummaryStatus.STALE
    assert saved.summary_due_at == clock.now() + timedelta(seconds=20)


async def test_running_the_job_twice_reads_the_source_once(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-3: taskiq may deliver a job twice; a source that is ready is left alone."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    added = await add_one(sources, student, notebook, FileInput(file_id=ref.id))

    await sources.process_source.execute(added.id)
    first = await passages_of(uow_factory, added.id)
    await sources.process_source.execute(added.id)

    assert world.files.read_calls == [ref.id]
    assert await passages_of(uow_factory, added.id) == first
    assert kicker.names().count(GUIDE_TASK) == 1


async def test_a_job_that_died_while_processing_is_run_again(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: a source left in `processing` is picked up by the next run."""
    stuck = await make_source(
        uow_factory,
        notebook,
        status=SourceStatus.PROCESSING,
        texts=(),
        body_md=TEXT,
    )

    await sources.process_source.execute(stuck.id)

    assert (await stored(uow_factory, stuck.id)).status is SourceStatus.READY


async def test_an_error_that_is_not_the_readers_is_retried_later(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NB-3: an unexpected error propagates; the source stays `processing`."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    added = await add_one(sources, student, notebook, FileInput(file_id=ref.id))
    original = world.files.read_text_with_pages
    attempts: list[int] = []

    async def flaky(file_id: UUID) -> FullText:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("storage is down")
        return await original(file_id)

    monkeypatch.setattr(world.files, "read_text_with_pages", flaky)

    with pytest.raises(RuntimeError):
        await sources.process_source.execute(added.id)
    assert (await stored(uow_factory, added.id)).status is SourceStatus.PROCESSING

    await sources.process_source.execute(added.id)
    assert (await stored(uow_factory, added.id)).status is SourceStatus.READY


@pytest.mark.parametrize(
    "status", [SourceStatus.READY, SourceStatus.FAILED, SourceStatus.UNAVAILABLE]
)
async def test_sources_that_are_not_waiting_are_left_alone(
    sources: SourcesServices,
    uow_factory: UowFactory,
    notebook: Notebook,
    status: SourceStatus,
) -> None:
    """NB-3: only pending, processing and stale sources are read."""
    source = await make_source(
        uow_factory, notebook, status=status, texts=(), body_md=TEXT
    )

    await sources.process_source.execute(source.id)

    assert (await stored(uow_factory, source.id)).status is status
    assert await passages_of(uow_factory, source.id) == []


async def test_unknown_sources_and_deleted_notebooks_are_skipped(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: nothing to do, and no error, for a source that is gone."""
    gone = await make_notebook(uow_factory, student.user_id, deleted_at=clock.now())
    waiting = await make_source(
        uow_factory, gone, status=SourceStatus.PENDING, texts=(), body_md=TEXT
    )

    await sources.process_source.execute(new_id())
    await sources.process_source.execute(waiting.id)

    assert (await stored(uow_factory, waiting.id)).status is SourceStatus.PENDING


# - - - Unchanged and changed text - - -


async def test_unchanged_text_keeps_passages_and_guide(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
    clock: FixedClock,
) -> None:
    """NB-3: the same content hash is a no-op for passages and for the guide."""
    found = world.flashcards.add_set(student.user_id)
    first = await add_ready(
        sources, uow_factory, student, notebook, FlashcardSetInput(set_id=found["id"])
    )
    await _set_guide(uow_factory, first.id)
    before = await passages_of(uow_factory, first.id)
    clock.advance(hours=1)

    await sources.sync_source.execute(student, notebook.id, first.id)
    await sources.process_source.execute(first.id)

    again = await stored(uow_factory, first.id)
    assert again.status is SourceStatus.READY
    assert again.guide_status is GuideStatus.READY
    assert again.guide is not None
    assert again.text_synced_at == clock.now()
    assert await passages_of(uow_factory, first.id) == before
    assert kicker.names().count(GUIDE_TASK) == 1


async def test_changed_text_replaces_passages_and_resets_the_guide(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-3, NB-4: new text means new passages, a new hash and a new guide job."""
    found = world.flashcards.add_set(student.user_id)
    first = await add_ready(
        sources, uow_factory, student, notebook, FlashcardSetInput(set_id=found["id"])
    )
    await _set_guide(uow_factory, first.id)
    old_ids = {p.id for p in await passages_of(uow_factory, first.id)}
    world.flashcards.append(found["id"], ("Nucleus", "Holds the DNA"))

    await sources.sync_source.execute(student, notebook.id, first.id)
    await sources.process_source.execute(first.id)

    again = await stored(uow_factory, first.id)
    assert again.content_hash != first.content_hash
    assert again.upstream_version != first.upstream_version
    assert again.guide is None
    assert again.guide_status is GuideStatus.NONE
    new = await passages_of(uow_factory, first.id)
    assert old_ids.isdisjoint({p.id for p in new})
    assert "Nucleus" in " ".join(p.text for p in new)
    assert kicker.names().count(GUIDE_TASK) == 2


# - - - Failures - - -


async def _failed(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    item: FileInput | UrlInput | ChatInput | LmsStepInput,
) -> SourceFailure:
    """Add and process an item that must end in `failed`; return the reason."""
    source = await add_ready(sources, uow_factory, student, notebook, item)
    assert source.status is SourceStatus.FAILED
    assert source.failure is not None
    assert await passages_of(uow_factory, source.id) == []
    saved = await stored_notebook(uow_factory, notebook.id)
    assert saved.char_count == 0
    assert saved.summary_status is SummaryStatus.NONE
    return source.failure


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("forbidden", SourceFailure.FORBIDDEN),
        ("fetch_failed", SourceFailure.FETCH_FAILED),
        ("unsupported_type", SourceFailure.UNSUPPORTED_TYPE),
        ("too_large", SourceFailure.TOO_LARGE),
        ("something_new", SourceFailure.PROVIDER_ERROR),
    ],
)
async def test_the_fetchers_failure_code_becomes_the_failure(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
    code: str,
    expected: SourceFailure,
) -> None:
    """NB-3: a reader's code is final (no retry); unknown codes are provider errors."""
    world.fetcher.fail(URL, code)

    failure = await _failed(sources, uow_factory, student, notebook, UrlInput(url=URL))

    assert failure is expected
    assert GUIDE_TASK not in kicker.names()


async def test_a_file_deleted_before_processing_fails_as_deleted(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: the file was removed between the request and the job."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    added = await add_one(sources, student, notebook, FileInput(file_id=ref.id))
    world.files.delete(ref.id)

    await sources.process_source.execute(added.id)

    saved = await stored(uow_factory, added.id)
    assert (saved.status, saved.failure) == (SourceStatus.FAILED, SourceFailure.DELETED)


async def test_a_file_that_lost_its_text_fails_as_no_text(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: the files module says there is no text sidecar."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    added = await add_one(sources, student, notebook, FileInput(file_id=ref.id))
    world.files.drop_text(ref.id)

    await sources.process_source.execute(added.id)

    saved = await stored(uow_factory, added.id)
    assert (saved.status, saved.failure) == (SourceStatus.FAILED, SourceFailure.NO_TEXT)


async def test_a_file_of_blank_text_fails_as_no_text(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: nothing is left after normalising."""
    ref = world.files.add_text(make_file(student.user_id), "  \n\n \t \n")

    failure = await _failed(
        sources, uow_factory, student, notebook, FileInput(file_id=ref.id)
    )

    assert failure is SourceFailure.NO_TEXT


@pytest.mark.parametrize("repeat", [30, 60])
async def test_text_over_the_cap_fails_as_too_large(
    build: Build,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    repeat: int,
) -> None:
    """NB-3: over the cap after normalising, and far over it before reading on."""
    sources = build(notebooks={"source_max_chars": 100})
    ref = world.files.add_text(make_file(student.user_id), "word " * repeat)

    failure = await _failed(
        sources, uow_factory, student, notebook, FileInput(file_id=ref.id)
    )

    assert failure is SourceFailure.TOO_LARGE


async def test_a_lms_step_fails_when_the_student_left_the_course(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3, LMS-17: enrolment is checked again when the text is read."""
    course = world.lms.add_course(enrolled=(student.user_id,))
    step = world.lms.add_step(course)
    added = await add_one(
        sources, student, notebook, LmsStepInput(course_id=course.id, step_id=step.id)
    )
    course.enrolled.clear()

    await sources.process_source.execute(added.id)

    saved = await stored(uow_factory, added.id)
    assert (saved.status, saved.failure) == (
        SourceStatus.FAILED,
        SourceFailure.FORBIDDEN,
    )


async def test_a_deleted_chat_fails_as_deleted(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: the chat was removed before it could be read."""
    chat = world.chats.add_chat(student.user_id)
    added = await add_one(sources, student, notebook, ChatInput(chat_id=chat.id))
    chat.deleted = True

    await sources.process_source.execute(added.id)

    saved = await stored(uow_factory, added.id)
    assert saved.kind is SourceKind.CHAT
    assert (saved.status, saved.failure) == (SourceStatus.FAILED, SourceFailure.DELETED)
