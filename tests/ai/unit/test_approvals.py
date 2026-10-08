"""AI-2, AI-3, AI-11: writes wait for approval, run once, can be rejected or expire."""

import asyncio
import json
from typing import Any
from uuid import UUID

from app.modules.ai.application.views import TurnResultView, TurnStatus
from app.modules.ai.domain.errors import (
    ToolCallExpiredError,
    ToolCallNotFoundError,
    ToolCallNotPendingError,
    TurnInProgressError,
)
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply
from tests.fakes.ai.stores import NoTurnLock

import pytest

CARDS = {
    "title": "Cells",
    "cards": [
        {"front": "Powerhouse?", "back": "Mitochondria"},
        {"front": "A", "back": "B"},
    ],
}


async def propose(h: AiHarness) -> tuple[UUID, str, TurnResultView]:
    """The assistant proposes creating a flash card set; return chat id and call id."""
    chat = await h.new_chat()
    h.llm.push(tool_reply(("create_flashcard_set", CARDS), text="Here is a set."))
    result = await h.say(chat.id, "make cards about cells")
    return chat.id, result.new_messages[-1].tool_calls[0].id, result


async def test_write_tool_waits_with_a_server_built_card(h: AiHarness) -> None:
    """AI-2, AI-3, AI-11: nothing is written; the card comes from the real arguments."""
    _, _, result = await propose(h)

    call = result.new_messages[-1].tool_calls[0]
    assert result.status is TurnStatus.AWAITING_APPROVAL
    assert (call.status, call.access) == ("pending_approval", "write")
    assert call.preview is not None
    assert call.preview.title == "Create flash card set “Cells” with 2 cards"
    assert call.preview.items == ["Powerhouse? → Mitochondria", "A → B"]
    assert call.expires_at == h.clock.now().replace(day=7)
    assert result.chat.pending_approvals == 1
    assert h.flashcards.create_calls == []
    assert len(h.llm.requests) == 1


async def test_approve_runs_the_write_and_the_assistant_continues(h: AiHarness) -> None:
    """UF-WEB-20: after Approve the set exists and the model sees the result."""
    chat_id, call_id, _ = await propose(h)
    h.llm.push(text_reply("Your set is ready."))

    result = await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat_id, call_id=call_id
    )

    assert result.status is TurnStatus.DONE
    assert [m.seq for m in result.new_messages] == [2, 3]
    assert result.new_messages[0].tool_calls[0].status == "done"
    assert result.new_messages[1].text == "Your set is ready."
    assert result.chat.pending_approvals == 0
    created = h.flashcards.create_calls
    assert len(created) == 1
    assert created[0]["source"] == "ai" and created[0]["chat_id"] == chat_id
    content = json.loads(h.llm.requests[1]["messages"][-1]["content"])
    assert content["untrusted_data"]["card_count"] == 2
    audit = h.store.audits[-1]
    assert (
        audit.type == "ai.write_approved"
        and audit.metadata["tool"] == "create_flashcard_set"
    )


async def test_a_second_approval_finds_the_call_already_done(h: AiHarness) -> None:
    """AI-11: the action can be approved only once (double tap, second tab)."""
    chat_id, call_id, _ = await propose(h)
    await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat_id, call_id=call_id
    )

    with pytest.raises(ToolCallNotPendingError):
        await h.services.approve_tool_call.execute(
            actor=h.student, chat_id=chat_id, call_id=call_id
        )
    assert len(h.flashcards.create_calls) == 1


async def test_concurrent_approvals_run_the_tool_once(
    make_harness: HarnessFactory,
) -> None:
    """UF-WEB-20 3e: of two concurrent approvals one runs the tool, one conflicts."""
    h = make_harness(lock=NoTurnLock())  # no turn lock: the claim alone must protect
    h.flashcards.delay = 0.01
    chat_id, call_id, _ = await propose(h)

    outcomes = await asyncio.gather(
        *[
            h.services.approve_tool_call.execute(
                actor=h.student, chat_id=chat_id, call_id=call_id
            )
            for _ in range(2)
        ],
        return_exceptions=True,
    )

    failures = [o for o in outcomes if isinstance(o, Exception)]
    assert len(failures) == 1 and isinstance(failures[0], ToolCallNotPendingError)
    assert failures[0].status == 409
    assert len(h.flashcards.create_calls) == 1


async def test_a_running_turn_blocks_a_second_request(h: AiHarness) -> None:
    """Only one turn per chat runs at a time."""
    chat = await h.new_chat()
    async with h.services.send_message.locks.hold(chat.id):
        with pytest.raises(TurnInProgressError):
            await h.say(chat.id, "hi")


async def test_reject_sends_the_reason_to_the_model(h: AiHarness) -> None:
    """AI-3: the rejection and the reason go back; the model may propose again."""
    chat_id, call_id, _ = await propose(h)
    h.llm.push(text_reply("I will make it shorter."))

    result = await h.services.reject_tool_call.execute(
        actor=h.student,
        chat_id=chat_id,
        call_id=call_id,
        reason="make the cards shorter",
    )

    assert result.new_messages[0].tool_calls[0].status == "rejected"
    assert (
        result.new_messages[0].tool_calls[0].reject_reason == "make the cards shorter"
    )
    assert h.flashcards.create_calls == []
    sent = json.loads(h.llm.requests[1]["messages"][-1]["content"])
    assert sent == {"rejected": True, "reason": "make the cards shorter"}
    assert result.chat.pending_approvals == 0


async def test_rejecting_twice_is_a_conflict(h: AiHarness) -> None:
    """AI-11: a decided call cannot be decided again."""
    chat_id, call_id, _ = await propose(h)
    await h.services.reject_tool_call.execute(
        actor=h.student, chat_id=chat_id, call_id=call_id, reason=None
    )

    with pytest.raises(ToolCallNotPendingError):
        await h.services.approve_tool_call.execute(
            actor=h.student, chat_id=chat_id, call_id=call_id
        )


async def test_a_new_message_supersedes_the_pending_card(h: AiHarness) -> None:
    """UF-WEB-20 3c: writing instead of deciding rejects the card as superseded."""
    chat_id, call_id, _ = await propose(h)
    h.llm.push(text_reply("Never mind."))

    result = await h.say(chat_id, "actually, forget it")

    superseded = result.new_messages[0]
    assert superseded.seq == 2 and superseded.tool_calls[0].status == "superseded"
    assert result.chat.pending_approvals == 0
    tool_result = next(m for m in h.llm.requests[1]["messages"] if m["role"] == "tool")
    assert "superseded" in json.loads(tool_result["content"])["error"]
    with pytest.raises(ToolCallNotPendingError):
        await h.services.approve_tool_call.execute(
            actor=h.student, chat_id=chat_id, call_id=call_id
        )


async def test_an_expired_card_cannot_be_approved(h: AiHarness) -> None:
    """AI-11: after 24 hours the card is gone (410) and shown as expired."""
    chat_id, call_id, _ = await propose(h)
    h.clock.advance(hours=25)

    with pytest.raises(ToolCallExpiredError) as caught:
        await h.services.approve_tool_call.execute(
            actor=h.student, chat_id=chat_id, call_id=call_id
        )

    assert caught.value.status == 410
    detail = await h.services.get_chat.execute(actor=h.student, chat_id=chat_id)
    assert detail.messages[1].tool_calls[0].status == "expired"
    assert detail.chat.pending_approvals == 0
    assert h.flashcards.create_calls == []


async def test_loading_a_chat_expires_old_cards_and_fixes_the_counter(
    h: AiHarness,
) -> None:
    """AI-11: lazy expiry updates the stored state and the pending count."""
    chat_id, _, _ = await propose(h)
    assert await h.services.public.pending_approvals(h.student.user_id) == 1
    h.clock.advance(hours=24, minutes=1)

    assert await h.services.public.pending_approvals(h.student.user_id) == 0
    assert (
        await h.services.get_chat.execute(actor=h.student, chat_id=chat_id)
    ).chat.pending_approvals == 0


async def test_unknown_call_id_is_not_found(h: AiHarness) -> None:
    """A call id that does not exist in the chat is a 404."""
    chat_id, _, _ = await propose(h)

    with pytest.raises(ToolCallNotFoundError):
        await h.services.approve_tool_call.execute(
            actor=h.student, chat_id=chat_id, call_id="nope"
        )


async def test_approval_rechecks_that_the_target_still_exists(h: AiHarness) -> None:
    """UF-WEB-20 3d: the set vanished before approval; the assistant is told why."""
    existing = await h.flashcards.create_set(
        h.student.user_id, "Old", [("a", "b")], source="manual"
    )
    chat = await h.new_chat()
    args = {"set_id": str(existing["id"]), "cards": [{"front": "x", "back": "y"}]}
    h.llm.push(tool_reply(("add_flashcards", args)))
    proposed = await h.say(chat.id, "add a card")
    call_id = proposed.new_messages[-1].tool_calls[0].id
    del h.flashcards.sets[existing["id"]]
    h.llm.push(text_reply("The set no longer exists."))

    result = await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=call_id
    )

    assert result.new_messages[0].tool_calls[0].status == "failed"
    error = json.loads(h.llm.requests[-1]["messages"][-1]["content"])["error"]
    assert "not found" in error


async def test_add_flashcards_to_a_missing_set_never_shows_a_card(h: AiHarness) -> None:
    """AI-11: a write that cannot work is refused when proposed, never shown."""
    chat = await h.new_chat()
    args: dict[str, Any] = {
        "set_id": str(UUID(int=9)),
        "cards": [{"front": "x", "back": "y"}],
    }
    h.llm.push(tool_reply(("add_flashcards", args)), text_reply("It does not exist."))

    result = await h.say(chat.id, "add a card")

    assert result.status is TurnStatus.DONE
    assert result.new_messages[1].tool_calls[0].status == "failed"
    assert result.chat.pending_approvals == 0


async def test_each_write_of_one_reply_has_its_own_card(h: AiHarness) -> None:
    """UF-ADM-12 2a: the assistant waits until every card is decided."""
    chat = await h.new_chat()
    h.llm.push(
        tool_reply(
            ("create_flashcard_set", CARDS),
            ("create_flashcard_set", {**CARDS, "title": "Second"}),
        )
    )
    proposed = await h.say(chat.id, "two sets")
    first, second = (c.id for c in proposed.new_messages[-1].tool_calls)
    assert proposed.chat.pending_approvals == 2
    h.llm.push(text_reply("Both created."))

    waiting = await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=first
    )
    finished = await h.services.reject_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=second, reason=None
    )

    assert waiting.status is TurnStatus.AWAITING_APPROVAL
    assert len(h.llm.requests) == 2  # no model call between the two decisions
    assert finished.status is TurnStatus.DONE
    assert [t["role"] for t in h.llm.requests[1]["messages"]].count("tool") == 2


async def test_approved_write_runs_even_when_the_budget_is_out(
    make_harness: HarnessFactory,
) -> None:
    """AI-8: the write runs; the answer waits for the reset (limit_reached)."""
    h = make_harness(limits={"ai_session_tokens_student": 12_000})
    chat = await h.new_chat()
    h.llm.push(tool_reply(("create_flashcard_set", CARDS), tokens=9_000))
    proposed = await h.say(chat.id, "cards")
    call_id = proposed.new_messages[-1].tool_calls[0].id

    result = await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=call_id
    )

    assert len(h.flashcards.create_calls) == 1
    assert result.status is TurnStatus.LIMIT_REACHED
    assert result.new_messages[0].tool_calls[0].status == "done"
