"""NB-6, NB-7: notebook chat messages in PostgreSQL."""

from datetime import timedelta

from app.modules.notebooks.domain.entities import (
    AnchorPassages,
    Citation,
    MessageContent,
    Notebook,
)
from app.modules.notebooks.domain.enums import MessageRole, SourceKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import (
    NOW,
    make_message,
    make_notebook,
    new_message_entity,
)

import pytest
from sqlalchemy.exc import IntegrityError


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A stored notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


async def test_add_then_get_returns_the_answer_with_citations_and_usage(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-6: an assistant answer round-trips with citations, anchor and token counts."""
    passage_id, source_id = new_id(), new_id()
    content = MessageContent(
        text="Plants make sugar ⟦1⟧.",
        citations=[
            Citation(
                n=1,
                passage_id=passage_id,
                source_id=source_id,
                source_title="Biology 10.pdf",
                source_kind=SourceKind.FILE,
                page=12,
                snippet="Photosynthesis makes sugar.",
            )
        ],
        followups=["What is chlorophyll?"],
        source_ids=[source_id],
        retrieval=True,
        grounded=True,
        anchor=AnchorPassages(ids=[passage_id]),
    )
    message = new_message_entity(
        notebook,
        seq=2,
        role=MessageRole.ASSISTANT,
        content=content,
        tokens_in=1200,
        tokens_out=300,
        tokens_cached=1000,
        weighted=1700,
        model="anthropic/claude-haiku-4.5",
        feedback=-1,
        stopped=True,
        created_at=NOW + timedelta(seconds=5),
    )

    async with uow_factory() as uow:
        await uow.messages.add(message)
        await uow.commit()
    async with uow_factory() as uow:
        loaded = await uow.messages.get(message.id)
        missing = await uow.messages.get(new_id())

    assert loaded == message
    assert missing is None


async def test_save_writes_feedback_stop_content_and_usage(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-7: feedback, a stopped stream and the final text are stored on the message."""
    message = await make_message(
        uow_factory, notebook, role=MessageRole.ASSISTANT, text="Partial"
    )
    message.content = MessageContent(text="Complete answer.", grounded=True)
    message.feedback = 1
    message.stopped = True
    message.tokens_in, message.tokens_out, message.weighted = 10, 20, 110
    message.model = "m"

    async with uow_factory() as uow:
        await uow.messages.save(message)
        await uow.commit()
    async with uow_factory() as uow:
        loaded = await uow.messages.get(message.id)
        await uow.messages.save(new_message_entity(notebook))

    assert loaded == message


async def test_seq_is_unique_per_thread_but_not_across_users(
    uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-6: a thread cannot have two messages with the same number."""
    await make_message(uow_factory, notebook, seq=1)
    await make_message(uow_factory, notebook, seq=1, user_id=new_id())

    async with uow_factory() as uow:
        with pytest.raises(IntegrityError):
            await uow.messages.add(new_message_entity(notebook, seq=1))


async def test_last_seq_is_per_thread(
    uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-6: the next message number comes from the user's own thread."""
    stranger = new_id()
    other_notebook = await make_notebook(uow_factory, student.user_id)
    async with uow_factory() as uow:
        assert await uow.messages.last_seq(notebook.id, student.user_id) == 0
    for _ in range(3):
        await make_message(uow_factory, notebook)
    await make_message(uow_factory, notebook, user_id=stranger)
    await make_message(uow_factory, other_notebook)

    async with uow_factory() as uow:
        assert await uow.messages.last_seq(notebook.id, notebook.owner_id) == 3
        assert await uow.messages.last_seq(notebook.id, stranger) == 1
        assert await uow.messages.last_seq(other_notebook.id, student.user_id) == 1
        assert await uow.messages.last_seq(new_id(), student.user_id) == 0


async def test_list_tail_returns_the_last_messages_oldest_first(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-6: the history for the model is the last N messages, in reading order."""
    for n in range(1, 8):
        await make_message(
            uow_factory,
            notebook,
            role=MessageRole.USER if n % 2 else MessageRole.ASSISTANT,
            text=f"m{n}",
        )
    await make_message(uow_factory, notebook, user_id=new_id(), text="stranger")

    async with uow_factory() as uow:
        tail = await uow.messages.list_tail(notebook.id, notebook.owner_id, 3)
        everything = await uow.messages.list_tail(notebook.id, notebook.owner_id, 50)

    assert [m.content.text for m in tail] == ["m5", "m6", "m7"]
    assert [m.seq for m in everything] == [1, 2, 3, 4, 5, 6, 7]


async def test_delete_removes_one_message(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-7: regenerate drops only the last answer."""
    first = await make_message(uow_factory, notebook, text="q")
    second = await make_message(
        uow_factory, notebook, role=MessageRole.ASSISTANT, text="a"
    )

    async with uow_factory() as uow:
        await uow.messages.delete(second.id)
        await uow.messages.delete(new_id())
        await uow.commit()
    async with uow_factory() as uow:
        left = await uow.messages.list_tail(notebook.id, notebook.owner_id, 10)

    assert [m.id for m in left] == [first.id]


async def test_delete_all_clears_only_one_users_thread(
    uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-7: "Delete chat history" reports how many messages went."""
    other_user = new_id()
    other_notebook = await make_notebook(uow_factory, student.user_id)
    for _ in range(3):
        await make_message(uow_factory, notebook)
    await make_message(uow_factory, notebook, user_id=other_user)
    await make_message(uow_factory, other_notebook)

    async with uow_factory() as uow:
        removed = await uow.messages.delete_all(notebook.id, notebook.owner_id)
        again = await uow.messages.delete_all(notebook.id, notebook.owner_id)
        mine = await uow.messages.list_tail(notebook.id, notebook.owner_id, 10)
        theirs = await uow.messages.list_tail(notebook.id, other_user, 10)
        elsewhere = await uow.messages.list_tail(other_notebook.id, student.user_id, 10)

    assert (removed, again, mine) == (3, 0, [])
    assert len(theirs) == 1 and len(elsewhere) == 1
