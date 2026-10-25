"""AI-1, AI-2: thumbs up or down on an assistant message."""

from uuid import UUID

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Feedback
from app.modules.ai.domain.errors import (
    ChatNotFoundError,
    FeedbackNotAllowedError,
    MessageNotFoundError,
    WrongAssistantError,
)
from app.shared.actor import Actor
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply

import pytest
from structlog.testing import capture_logs

SECRET = "my private remark about the teacher"


async def answered_chat(h: AiHarness) -> UUID:
    """A chat with one user message (seq 1) and one answer (seq 2)."""
    chat = await h.new_chat()
    h.llm.push(text_reply("The answer."))
    await h.say(chat.id, "A question")
    chat_id: UUID = chat.id
    return chat_id


async def rate(
    h: AiHarness,
    chat_id: UUID,
    seq: int,
    rating: Feedback,
    comment: str | None = None,
    actor: Actor | None = None,
) -> None:
    """Run the use case as the student (or the given actor)."""
    await h.services.set_message_feedback.execute(
        actor=actor or h.student,
        chat_id=chat_id,
        seq=seq,
        rating=rating,
        comment=comment,
    )


def stored_feedback(h: AiHarness, chat_id: UUID, seq: int) -> tuple[object, object]:
    """The (rating, comment) kept on a stored message."""
    message = next(m for m in h.store.chat_messages(chat_id) if m.seq == seq)
    return message.feedback, message.feedback_comment


async def test_a_rating_is_stored_and_shown_in_the_chat(h: AiHarness) -> None:
    """AI-1: the thumb is kept on the message and returned with the chat."""
    chat_id = await answered_chat(h)

    await rate(h, chat_id, 2, Feedback.UP)

    detail = await h.services.get_chat.execute(actor=h.student, chat_id=chat_id)
    assert [m.feedback for m in detail.messages] == [None, "up"]
    assert stored_feedback(h, chat_id, 2) == (Feedback.UP, None)


async def test_a_new_rating_replaces_the_old_one(h: AiHarness) -> None:
    """AI-1: up then down leaves down, and the old comment goes with the old rating."""
    chat_id = await answered_chat(h)
    await rate(h, chat_id, 2, Feedback.UP, "nice")

    await rate(h, chat_id, 2, Feedback.DOWN)

    assert stored_feedback(h, chat_id, 2) == (Feedback.DOWN, None)


async def test_the_same_rating_again_keeps_it_and_its_comment(h: AiHarness) -> None:
    """AI-1: repeating a thumb is harmless; a new comment updates the comment."""
    chat_id = await answered_chat(h)
    await rate(h, chat_id, 2, Feedback.DOWN, "too long")

    await rate(h, chat_id, 2, Feedback.DOWN)
    assert stored_feedback(h, chat_id, 2) == (Feedback.DOWN, "too long")

    await rate(h, chat_id, 2, Feedback.DOWN, "  wrong language ")
    assert stored_feedback(h, chat_id, 2) == (Feedback.DOWN, "wrong language")


async def test_a_blank_comment_is_no_comment(h: AiHarness) -> None:
    """AI-1: whitespace only is stored as nothing."""
    chat_id = await answered_chat(h)

    await rate(h, chat_id, 2, Feedback.UP, "   ")

    assert stored_feedback(h, chat_id, 2) == (Feedback.UP, None)


async def test_only_assistant_messages_can_be_rated(h: AiHarness) -> None:
    """AI-1: a user message is a 422; a missing seq is a 404."""
    chat_id = await answered_chat(h)

    with pytest.raises(FeedbackNotAllowedError) as user_message:
        await rate(h, chat_id, 1, Feedback.UP)
    with pytest.raises(MessageNotFoundError) as missing:
        await rate(h, chat_id, 9, Feedback.UP)

    assert (user_message.value.status, user_message.value.code) == (
        422,
        "ai/feedback-not-allowed",
    )
    assert (missing.value.status, missing.value.code) == (404, "ai/message-not-found")
    assert stored_feedback(h, chat_id, 1) == (None, None)


async def test_rating_belongs_to_the_owner_of_the_chat(h: AiHarness) -> None:
    """AI-1: other people and deleted chats get not-found; roles are checked."""
    chat_id = await answered_chat(h)

    with pytest.raises(ChatNotFoundError):
        await rate(h, chat_id, 2, Feedback.UP, actor=h.other_student)
    await h.services.delete_chat.execute(actor=h.student, chat_id=chat_id)
    with pytest.raises(ChatNotFoundError):
        await rate(h, chat_id, 2, Feedback.UP)

    assert stored_feedback(h, chat_id, 2) == (None, None)


async def test_rating_a_chat_of_the_other_assistant_is_forbidden(
    h: AiHarness,
) -> None:
    """AI-1: a student cannot rate inside an Administration chat they own."""
    chat = await h.new_chat(assistant=Assistant.ADMIN)
    h.store.chats[chat.id].owner_id = h.student.user_id

    with pytest.raises(WrongAssistantError):
        await rate(h, chat.id, 1, Feedback.UP)


async def test_the_old_rating_is_gone_with_a_regenerated_answer(h: AiHarness) -> None:
    """AI-2: the new answer starts without a thumb."""
    chat_id = await answered_chat(h)
    await rate(h, chat_id, 2, Feedback.DOWN, "bad")
    h.llm.push(text_reply("A better answer."))

    await h.services.regenerate_answer.execute(actor=h.student, chat_id=chat_id)

    detail = await h.services.get_chat.execute(actor=h.student, chat_id=chat_id)
    assert [m.feedback for m in detail.messages] == [None, None]


async def test_the_comment_is_never_logged(h: AiHarness) -> None:
    """AI-1: not on success, and not when the rating is refused."""
    chat_id = await answered_chat(h)

    with capture_logs() as logs:
        await rate(h, chat_id, 2, Feedback.DOWN, SECRET)
        with pytest.raises(FeedbackNotAllowedError):
            await rate(h, chat_id, 1, Feedback.DOWN, SECRET)

    assert SECRET not in repr(logs)
    assert all(SECRET not in repr(audit) for audit in h.store.audits)
