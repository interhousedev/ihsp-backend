"""NB-3, NB-8: outdated chats and upstream sources, and the Sync button."""

from app.modules.notebooks.domain.entities import (
    Citation,
    MessageContent,
    Notebook,
)
from app.modules.notebooks.domain.enums import MessageRole, SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import (
    NotebookNotFoundError,
    SourceNotReadyError,
)
from app.modules.notebooks.domain.source_input import (
    ChatInput,
    LmsStepInput,
    TextInput,
    UrlInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_message
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.support import (
    PROCESS_TASK,
    add_one,
    add_ready,
    passages_of,
    stored,
)

import pytest

SNIPPET = "Plants turn light into sugar."


async def test_a_chat_with_new_messages_is_outdated_until_it_is_synced(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-3, NB-8: stale is still usable; sync re-reads up to the latest message."""
    chat = world.chats.add_chat(student.user_id)
    ready = await add_ready(
        sources, uow_factory, student, notebook, ChatInput(chat_id=chat.id)
    )
    old = await passages_of(uow_factory, ready.id)
    citation = Citation(
        n=1,
        passage_id=old[0].id,
        source_id=ready.id,
        source_title=ready.title,
        source_kind=SourceKind.CHAT,
        snippet=SNIPPET,
    )
    await make_message(
        uow_factory,
        notebook,
        role=MessageRole.ASSISTANT,
        content=MessageContent(text="Light becomes sugar ⟦1⟧.", citations=[citation]),
    )
    world.chats.say(chat.id, "user", "And the light reactions?")
    world.chats.say(chat.id, "assistant", "They split water in the thylakoids.")

    assert await sources.sweep_sources.execute() == 1
    outdated = await stored(uow_factory, ready.id)
    assert outdated.status is SourceStatus.STALE
    assert outdated.usable
    assert await passages_of(uow_factory, ready.id) == old

    synced = await sources.sync_source.execute(student, notebook.id, ready.id)
    assert synced.status is SourceStatus.PENDING
    assert synced.ref["until_seq"] is None
    assert kicker.calls[-1] == (PROCESS_TASK, {"source_id": str(ready.id)})

    await sources.process_source.execute(ready.id)
    fresh = await stored(uow_factory, ready.id)
    assert fresh.status is SourceStatus.READY
    assert fresh.ref["until_seq"] == 6
    assert fresh.upstream_version == "6"
    assert len(await passages_of(uow_factory, ready.id)) == 3
    async with uow_factory() as uow:
        assert await uow.passages.get(old[0].id, notebook.id) is None
        thread = await uow.messages.list_tail(notebook.id, student.user_id, 10)
    assert thread[0].content.citations == [citation]


async def test_syncing_a_chat_snapshot_moves_it_to_the_latest_message(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-8: a chat added up to message 2 reads all four messages after Sync."""
    chat = world.chats.add_chat(student.user_id)
    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        ChatInput(chat_id=chat.id, until_seq=2),
    )
    assert len(await passages_of(uow_factory, ready.id)) == 1

    await sources.sync_source.execute(student, notebook.id, ready.id)
    await sources.process_source.execute(ready.id)

    fresh = await stored(uow_factory, ready.id)
    assert fresh.ref["until_seq"] == 4
    assert len(await passages_of(uow_factory, ready.id)) == 2


async def test_a_changed_lms_revision_is_outdated_and_sync_reads_it(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-8, LMS-17: the live revision id decides; the new text has no test blocks."""
    course = world.lms.add_course(enrolled=(student.user_id,))
    step = world.lms.add_step(course)
    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LmsStepInput(course_id=course.id, step_id=step.id),
    )
    step.blocks[0] = ("text", "A cell membrane controls what enters the cell.")
    step.revision = 2

    assert await sources.sweep_sources.execute() == 1
    assert (await stored(uow_factory, ready.id)).status is SourceStatus.STALE

    await sources.sync_source.execute(student, notebook.id, ready.id)
    await sources.process_source.execute(ready.id)

    fresh = await stored(uow_factory, ready.id)
    assert (fresh.status, fresh.upstream_version) == (SourceStatus.READY, "rev-2")
    text = " ".join(p.text for p in await passages_of(uow_factory, ready.id))
    assert "cell membrane" in text
    assert "correct: B" not in text


async def test_a_failed_page_can_be_synced_again(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-8: Sync retries a web page that could not be fetched."""
    url = "http://example.com/a"
    world.fetcher.fail(url, "fetch_failed")
    failed = await add_ready(sources, uow_factory, student, notebook, UrlInput(url=url))
    assert failed.status is SourceStatus.FAILED
    world.fetcher.failures.clear()
    world.fetcher.add_page(url, SNIPPET)

    again = await sources.sync_source.execute(student, notebook.id, failed.id)
    assert (again.status, again.failure) == (SourceStatus.PENDING, None)
    await sources.process_source.execute(failed.id)

    assert (await stored(uow_factory, failed.id)).status is SourceStatus.READY


async def test_kinds_without_an_upstream_come_back_unchanged(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-8: pasted text has nothing to sync; no job is queued."""
    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        TextInput(title="Notes", text=SNIPPET),
    )
    queued = len(kicker.calls)

    result = await sources.sync_source.execute(student, notebook.id, ready.id)

    assert result.status is SourceStatus.READY
    assert len(kicker.calls) == queued


async def test_a_source_that_is_still_processing_cannot_be_synced(
    sources: SourcesServices,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-8: `source-not-ready` while the first read is still queued."""
    chat = world.chats.add_chat(student.user_id)
    pending = await add_one(sources, student, notebook, ChatInput(chat_id=chat.id))

    with pytest.raises(SourceNotReadyError):
        await sources.sync_source.execute(student, notebook.id, pending.id)


async def test_only_the_owner_can_sync(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """NB-15: another student, or the wrong notebook, gets a 404."""
    chat = world.chats.add_chat(student.user_id)
    ready = await add_ready(
        sources, uow_factory, student, notebook, ChatInput(chat_id=chat.id)
    )

    with pytest.raises(NotebookNotFoundError):
        await sources.sync_source.execute(other_student, notebook.id, ready.id)
    with pytest.raises(NotebookNotFoundError):
        await sources.sync_source.execute(other_student, their_notebook.id, ready.id)
