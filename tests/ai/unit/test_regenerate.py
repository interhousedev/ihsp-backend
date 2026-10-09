"""AI-2, AI-8, AI-11: "Regenerate" answers the last user message again."""

import json
from uuid import UUID

from app.modules.ai.application.views import TurnResultView, TurnStatus
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import ChatTier
from app.modules.ai.domain.errors import (
    AiLimitReachedError,
    AiProviderError,
    ApprovalPendingError,
    ChatNotFoundError,
    NothingToRegenerateError,
)
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import provider_error, text_reply, tool_reply

import pytest

CARDS = {"title": "Cells", "cards": [{"front": "Q", "back": "A"}]}


async def regenerate(
    h: AiHarness, chat_id: UUID, actor: Actor | None = None
) -> TurnResultView:
    """Run the use case as the student (or the given actor)."""
    return await h.services.regenerate_answer.execute(
        actor=actor or h.student, chat_id=chat_id
    )


def stored(h: AiHarness, chat_id: UUID) -> list[tuple[int, str, str]]:
    """The stored messages as (seq, role, text)."""
    return [(m.seq, m.role.value, m.text) for m in h.store.chat_messages(chat_id)]


async def test_regenerate_replaces_only_the_last_answer(h: AiHarness) -> None:
    """AI-2: earlier turns stay; the model answers the last message again."""
    chat = await h.new_chat()
    h.llm.push(text_reply("first answer"), text_reply("second answer"))
    await h.say(chat.id, "one")
    await h.say(chat.id, "two")
    h.llm.push(text_reply("better answer"))

    result = await regenerate(h, chat.id)

    assert result.status is TurnStatus.DONE
    assert [(m.seq, m.role, m.text) for m in result.new_messages] == [
        (4, "assistant", "better answer")
    ]
    assert stored(h, chat.id) == [
        (1, "user", "one"),
        (2, "assistant", "first answer"),
        (3, "user", "two"),
        (4, "assistant", "better answer"),
    ]
    request = h.llm.requests[-1]
    assert request["messages"][-1] == {"role": "user", "content": "two"}
    assert "second answer" not in json.dumps(request["messages"])
    assert result.chat.title == "one"


async def test_regenerate_removes_the_tool_steps_of_the_old_answer(
    h: AiHarness,
) -> None:
    """AI-2: every message after the last user message goes, tool calls included."""
    chat = await h.new_chat()
    h.llm.push(tool_reply(("get_my_subjects", {})), text_reply("old answer"))
    first = await h.say(chat.id, "my subjects")
    assert [m.seq for m in first.new_messages] == [1, 2, 3]
    h.llm.push(text_reply("new answer"))

    result = await regenerate(h, chat.id)

    assert stored(h, chat.id) == [
        (1, "user", "my subjects"),
        (2, "assistant", "new answer"),
    ]
    assert [m.seq for m in result.new_messages] == [2]
    assert all(not m.tool_calls for m in h.store.chat_messages(chat.id))


async def test_regenerate_can_be_repeated(h: AiHarness) -> None:
    """AI-2: sequence numbers stay gap-free over several regenerations."""
    chat = await h.new_chat()
    await h.say(chat.id, "hello")
    for attempt in ("second", "third"):
        h.llm.push(text_reply(attempt))
        await regenerate(h, chat.id)

    assert stored(h, chat.id) == [(1, "user", "hello"), (2, "assistant", "third")]


async def test_regenerate_counts_the_tokens_it_uses(h: AiHarness) -> None:
    """AI-9: both the old and the new request are counted in the budget."""
    chat = await h.new_chat()
    await h.say(chat.id, "hello")

    result = await regenerate(h, chat.id)

    assert result.usage.session.used == 240
    assert result.usage.day.used == 240


async def test_regenerate_is_refused_while_an_approval_waits(h: AiHarness) -> None:
    """AI-11: a pending card must be decided first; nothing is removed."""
    chat = await h.new_chat()
    h.llm.push(tool_reply(("create_flashcard_set", CARDS)))
    await h.say(chat.id, "make cards")
    asked = len(h.llm.requests)

    with pytest.raises(ApprovalPendingError) as caught:
        await regenerate(h, chat.id)

    assert (caught.value.status, caught.value.code) == (409, "ai/approval-pending")
    assert len(h.llm.requests) == asked
    messages = h.store.chat_messages(chat.id)
    assert [m.seq for m in messages] == [1, 2] and messages[1].pending_calls()
    assert h.store.chats[chat.id].pending_approvals == 1


async def test_an_expired_approval_does_not_block_regenerate(h: AiHarness) -> None:
    """AI-11: a card older than 24 hours counts as expired, not as waiting."""
    chat = await h.new_chat()
    h.llm.push(tool_reply(("create_flashcard_set", CARDS)))
    await h.say(chat.id, "make cards")
    h.clock.advance(hours=25)
    h.llm.push(text_reply("Fresh answer"))

    result = await regenerate(h, chat.id)

    assert result.status is TurnStatus.DONE
    assert stored(h, chat.id) == [
        (1, "user", "make cards"),
        (2, "assistant", "Fresh answer"),
    ]
    assert h.store.chats[chat.id].pending_approvals == 0


async def test_regenerate_does_not_undo_a_write_that_was_approved(
    h: AiHarness,
) -> None:
    """AI-2, AI-3: an approved write stays done; only the messages are replaced."""
    chat = await h.new_chat()
    h.llm.push(tool_reply(("create_flashcard_set", CARDS)), text_reply("Created."))
    proposed = await h.say(chat.id, "make cards")
    call_id = proposed.new_messages[-1].tool_calls[0].id
    await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=call_id
    )
    h.llm.push(text_reply("Here is another way to say it."))

    await regenerate(h, chat.id)

    assert stored(h, chat.id) == [
        (1, "user", "make cards"),
        (2, "assistant", "Here is another way to say it."),
    ]
    assert len(h.flashcards.create_calls) == 1


async def test_regenerate_honours_the_budget_and_keeps_the_answer(
    make_harness: HarnessFactory,
) -> None:
    """AI-8: over the limit it is 429 before anything is removed."""
    h = make_harness(limits={"ai_daily_tokens_student": 20_000})
    chat = await h.new_chat()
    h.llm.push(text_reply("a", tokens=16_000))
    await h.say(chat.id, "one")

    with pytest.raises(AiLimitReachedError) as caught:
        await regenerate(h, chat.id)

    assert caught.value.status == 429 and caught.value.params["scope"] == "day"
    assert len(h.llm.requests) == 1
    assert stored(h, chat.id) == [(1, "user", "one"), (2, "assistant", "a")]


async def test_regenerate_belongs_to_the_owner(h: AiHarness) -> None:
    """AI-1: other people (and deleted chats) get not-found, nothing changes."""
    chat = await h.new_chat()
    await h.say(chat.id, "mine")
    asked = len(h.llm.requests)

    with pytest.raises(ChatNotFoundError):
        await regenerate(h, chat.id, actor=h.other_student)
    with pytest.raises(ChatNotFoundError):
        await regenerate(h, chat.id, actor=h.admin)
    await h.services.delete_chat.execute(actor=h.student, chat_id=chat.id)
    with pytest.raises(ChatNotFoundError):
        await regenerate(h, chat.id)

    assert len(h.llm.requests) == asked
    assert [m.seq for m in h.store.chat_messages(chat.id)] == [1, 2]


async def test_an_empty_chat_has_nothing_to_regenerate(h: AiHarness) -> None:
    """AI-2: no user message means a 409 problem."""
    chat = await h.new_chat()

    with pytest.raises(NothingToRegenerateError) as caught:
        await regenerate(h, chat.id)

    assert (caught.value.status, caught.value.code) == (
        409,
        "ai/nothing-to-regenerate",
    )
    assert h.llm.requests == []


async def test_regenerate_retries_a_turn_whose_request_failed(h: AiHarness) -> None:
    """AI-2: with no answer stored the message is simply answered again."""
    chat = await h.new_chat()
    h.llm.push(provider_error())
    with pytest.raises(AiProviderError):
        await h.say(chat.id, "hello")
    assert stored(h, chat.id) == [(1, "user", "hello")]
    h.llm.push(text_reply("hi"))

    result = await regenerate(h, chat.id)

    assert [(m.seq, m.text) for m in result.new_messages] == [(2, "hi")]
    assert stored(h, chat.id) == [(1, "user", "hello"), (2, "assistant", "hi")]


async def test_the_administration_assistant_can_regenerate_too(h: AiHarness) -> None:
    """AI-1, AI-2: the same route works for the admin assistant and its model."""
    chat = await h.new_chat(assistant=Assistant.ADMIN)
    await h.say(chat.id, "status?", actor=h.admin)
    h.llm.push(text_reply("second try"))

    result = await regenerate(h, chat.id, actor=h.admin)

    assert [m.text for m in result.new_messages] == ["second try"]
    assert h.llm.requests[-1]["model"] == h.settings.ai_profile(AiTask.ADMIN_CHAT).model


async def test_regenerate_marks_the_chat_as_active(h: AiHarness) -> None:
    """AI-1: the chat moves to the top of the list after a new answer."""
    chat = await h.new_chat()
    await h.say(chat.id, "hello")
    h.clock.advance(minutes=10)

    result = await regenerate(h, chat.id)

    assert result.chat.last_message_at == h.clock.now()


async def test_regenerate_uses_the_model_of_the_chat_tier(h: AiHarness) -> None:
    """AI-13: a regenerated answer comes from the model of the chat's tier."""
    chat = await h.services.create_chat.execute(
        actor=h.student, assistant=Assistant.STUDENT, tier=ChatTier.SMART
    )
    await h.say(chat.id, "hello")

    await regenerate(h, chat.id)

    smart = h.settings.ai_profile(AiTask.STUDENT_CHAT_SMART).model
    assert [r["model"] for r in h.llm.requests] == [smart, smart]
