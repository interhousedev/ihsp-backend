"""NB-6, NB-15: reading, clearing and rating the chat thread (§ 3.3.6, § 4.3)."""

from typing import Literal
from uuid import UUID

from app.modules.notebooks.domain.entities import MessageContent, Notebook
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.domain.errors import BusyError, NotebookNotFoundError
from app.modules.notebooks.wiring_chat import ChatServices
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import make_message, new_message_entity
from tests.notebooks.unit.chat.support import notebook_with_source, thread

import pytest


async def add_messages(
    core: NotebooksCore, notebook: Notebook, user_id: UUID, count: int
) -> None:
    """Store `count` alternating messages for a user in one transaction."""
    async with core.uow_factory() as uow:
        for seq in range(1, count + 1):
            role = MessageRole.USER if seq % 2 else MessageRole.ASSISTANT
            await uow.messages.add(
                new_message_entity(
                    notebook,
                    user_id=user_id,
                    seq=seq,
                    role=role,
                    content=MessageContent(text=f"m{seq}"),
                )
            )
        await uow.commit()


# - - - reading - - -


async def test_the_chat_of_a_new_notebook_is_empty(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: no messages yet."""
    notebook, _ = await notebook_with_source(core, student)

    assert await chat.get_chat.execute(student, notebook.id) == []


async def test_the_last_200_messages_are_returned_oldest_first(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: `GET chat` returns the tail of the thread in ascending order."""
    notebook, _ = await notebook_with_source(core, student)
    await add_messages(core, notebook, student.user_id, 205)

    messages = await chat.get_chat.execute(student, notebook.id)

    assert len(messages) == 200
    assert [m.seq for m in messages] == list(range(6, 206))
    assert messages[0].content.text == "m6" and messages[-1].content.text == "m205"


async def test_only_the_callers_own_thread_is_returned(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-15: messages of another user in the same notebook are not shown."""
    notebook, _ = await notebook_with_source(core, student)
    await add_messages(core, notebook, student.user_id, 2)
    await add_messages(core, notebook, new_id(), 4)

    messages = await chat.get_chat.execute(student, notebook.id)

    assert [m.content.text for m in messages] == ["m1", "m2"]


async def test_another_students_chat_is_not_found(
    core: NotebooksCore, chat: ChatServices, student: Actor, other_student: Actor
) -> None:
    """NB-15: 404 for a notebook that is not yours."""
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(NotebookNotFoundError):
        await chat.get_chat.execute(other_student, notebook.id)


# - - - deleting the history - - -


async def test_deleting_the_chat_clears_only_the_callers_thread(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: `DELETE chat` removes the student's messages, nobody else's."""
    notebook, _ = await notebook_with_source(core, student)
    await add_messages(core, notebook, student.user_id, 4)
    stranger = new_id()
    await add_messages(core, notebook, stranger, 2)

    await chat.delete_chat.execute(student, notebook.id)

    assert await chat.get_chat.execute(student, notebook.id) == []
    async with core.uow_factory() as uow:
        assert len(await uow.messages.list_tail(notebook.id, stranger, 10)) == 2


async def test_a_new_conversation_starts_at_seq_one_after_deleting(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: the next question is the first message again."""
    notebook, _ = await notebook_with_source(core, student)
    await chat.ask_notebook.execute(student, notebook.id, "Before?")
    await chat.delete_chat.execute(student, notebook.id)

    turn = await chat.ask_notebook.execute(student, notebook.id, "After?")

    assert (turn.user_message.seq, turn.assistant_message.seq) == (1, 2)


async def test_deleting_someone_elses_chat_is_not_found(
    core: NotebooksCore, chat: ChatServices, student: Actor, other_student: Actor
) -> None:
    """NB-15: 404, and nothing is deleted."""
    notebook, _ = await notebook_with_source(core, student)
    await add_messages(core, notebook, student.user_id, 2)

    with pytest.raises(NotebookNotFoundError):
        await chat.delete_chat.execute(other_student, notebook.id)

    assert len(await thread(core, student, notebook)) == 2


async def test_the_history_cannot_be_deleted_while_a_question_runs(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: a running question would store its answer into a cleared thread."""
    notebook, _ = await notebook_with_source(core, student)
    await add_messages(core, notebook, student.user_id, 2)

    async with core.turn_lock.hold(notebook.id, student.user_id):
        with pytest.raises(BusyError):
            await chat.delete_chat.execute(student, notebook.id)

    assert len(await thread(core, student, notebook)) == 2


# - - - feedback - - -


@pytest.mark.parametrize(("rating", "stored"), [("up", 1), ("down", -1)])
async def test_a_rating_is_stored_on_the_answer(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    rating: Literal["up", "down"],
    stored: int,
) -> None:
    """NB-18: up is 1, down is -1."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    await chat.message_feedback.execute(
        student, notebook.id, turn.assistant_message.id, rating
    )

    messages = await chat.get_chat.execute(student, notebook.id)
    assert [m.feedback for m in messages] == [None, stored]


async def test_a_new_rating_replaces_the_old_one(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-18: the last thumb wins."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    answer_id = turn.assistant_message.id
    await chat.message_feedback.execute(student, notebook.id, answer_id, "up")

    await chat.message_feedback.execute(student, notebook.id, answer_id, "down")

    messages = await chat.get_chat.execute(student, notebook.id)
    assert messages[1].feedback == -1


async def test_the_comment_is_not_stored(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-16: the free text of a rating is neither kept nor returned."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    await chat.message_feedback.execute(
        student, notebook.id, turn.assistant_message.id, "down", "my private reason"
    )

    messages = await chat.get_chat.execute(student, notebook.id)
    assert "private reason" not in repr(messages)


async def test_a_question_cannot_be_rated(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-18: only the assistant's messages take feedback."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    with pytest.raises(NotebookNotFoundError):
        await chat.message_feedback.execute(
            student, notebook.id, turn.user_message.id, "up"
        )


async def test_an_unknown_message_is_not_found(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-18: a random id answers 404."""
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(NotebookNotFoundError):
        await chat.message_feedback.execute(student, notebook.id, new_id(), "up")


async def test_a_message_of_another_notebook_cannot_be_rated_through_this_one(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-15: the message must belong to the notebook in the path."""
    notebook, _ = await notebook_with_source(core, student)
    elsewhere, _ = await notebook_with_source(core, student)
    answer = await make_message(
        core.uow_factory, elsewhere, role=MessageRole.ASSISTANT, text="Hi"
    )

    with pytest.raises(NotebookNotFoundError):
        await chat.message_feedback.execute(student, notebook.id, answer.id, "up")


async def test_another_students_answer_cannot_be_rated(
    core: NotebooksCore, chat: ChatServices, student: Actor, other_student: Actor
) -> None:
    """NB-15: neither through their notebook nor through your own."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    mine, _ = await notebook_with_source(core, other_student)

    for path in (notebook.id, mine.id):
        with pytest.raises(NotebookNotFoundError):
            await chat.message_feedback.execute(
                other_student, path, turn.assistant_message.id, "up"
            )

    messages = await chat.get_chat.execute(student, notebook.id)
    assert messages[1].feedback is None


async def test_a_message_of_another_user_in_the_same_notebook_cannot_be_rated(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-15: the thread is per user (ready for shared notebooks)."""
    notebook, _ = await notebook_with_source(core, student)
    answer = await make_message(
        core.uow_factory,
        notebook,
        role=MessageRole.ASSISTANT,
        text="Hi",
        user_id=new_id(),
    )

    with pytest.raises(NotebookNotFoundError):
        await chat.message_feedback.execute(student, notebook.id, answer.id, "up")
