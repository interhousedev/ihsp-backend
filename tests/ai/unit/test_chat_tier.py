"""AI-1, AI-8, AI-13: the fast and smart tiers of a student chat."""

from app.modules.ai.application.views import ChatItemView
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import (
    ChatMessage,
    ChatTier,
    MessageContent,
    MessageRole,
)
from app.modules.ai.domain.errors import AiLimitReachedError
from app.settings_ai import AiTaskSettings
from app.shared.ai_tasks import AiTask
from app.shared.ids import new_id
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest
from pydantic import ValidationError


async def smart_chat(h: AiHarness) -> ChatItemView:
    """A new student chat on the smart tier."""
    return await h.services.create_chat.execute(
        actor=h.student, assistant=Assistant.STUDENT, tier=ChatTier.SMART
    )


async def test_a_chat_is_fast_unless_the_user_picks_smart(h: AiHarness) -> None:
    """AI-13: the default tier uses the configured student model."""
    default = await h.new_chat()
    fast = await h.services.create_chat.execute(
        actor=h.student, assistant=Assistant.STUDENT, tier=ChatTier.FAST
    )

    assert default.tier == fast.tier == "fast"
    for chat in (default, fast):
        stored = h.store.chats[chat.id]
        assert stored.tier is ChatTier.FAST
        assert stored.model == h.settings.ai_profile(AiTask.STUDENT_CHAT).model


async def test_a_smart_chat_stores_its_tier_and_uses_the_smart_model(
    h: AiHarness,
) -> None:
    """AI-13: `smart` maps to the STUDENT_CHAT_SMART model on every message."""
    chat = await smart_chat(h)

    await h.say(chat.id, "one")
    await h.say(chat.id, "two")

    smart = h.settings.ai_profile(AiTask.STUDENT_CHAT_SMART).model
    assert smart == "anthropic/claude-sonnet-5.5" and chat.tier == "smart"
    stored = h.store.chats[chat.id]
    assert (stored.tier, stored.model) == (ChatTier.SMART, smart)
    assert [r["model"] for r in h.llm.requests] == [smart, smart]


async def test_the_tier_is_shown_in_the_list_and_the_chat(h: AiHarness) -> None:
    """AI-1: ChatItem and ChatDetail carry `tier`."""
    chat = await smart_chat(h)

    page = await h.services.list_chats.execute(
        actor=h.student, assistant=Assistant.STUDENT, cursor=None, limit=20
    )
    detail = await h.services.get_chat.execute(actor=h.student, chat_id=chat.id)

    assert [c.tier for c in page.items] == ["smart"]
    assert detail.chat.tier == "smart"


async def test_a_smart_turn_counts_its_weight_in_the_budget(h: AiHarness) -> None:
    """AI-8: 120 real tokens cost 4 x 120 of the budget; the message keeps 100/20."""
    chat = await smart_chat(h)

    result = await h.say(chat.id, "hello")

    assert result.usage.session.used == 480 and result.usage.day.used == 480
    message = h.store.chat_messages(chat.id)[-1]
    assert (message.tokens_in, message.tokens_out) == (100, 20)


async def test_every_step_of_a_smart_turn_is_weighted(h: AiHarness) -> None:
    """AI-9: tool loops are counted per request, each times the weight."""
    chat = await smart_chat(h)
    h.llm.push(tool_reply(("get_my_subjects", {})), text_reply("done"))

    result = await h.say(chat.id, "my subjects")

    assert result.usage.session.used == (120 + 120) * 4


async def test_the_weight_is_a_setting(make_harness: HarnessFactory) -> None:
    """AI-8: the task's budget_weight sets the factor; fast chats stay at 1."""
    h = make_harness(tasks={AiTask.STUDENT_CHAT_SMART: AiTaskSettings(budget_weight=2)})
    smart = await smart_chat(h)
    fast = await h.new_chat()

    smart_result = await h.say(smart.id, "hello")
    fast_result = await h.say(fast.id, "hello")

    assert smart_result.usage.session.used == 240
    assert fast_result.usage.session.used == 240 + 120


def test_the_weight_must_be_at_least_one() -> None:
    """AI-8: a weight below 1 would make smart cheaper than fast."""
    with pytest.raises(ValidationError):
        AiTaskSettings(budget_weight=0)


async def test_the_budget_check_before_a_request_uses_the_weight(
    make_harness: HarnessFactory,
) -> None:
    """AI-8: the same request fits a fast chat but not a smart one."""
    h = make_harness(limits={"ai_daily_tokens_student": 20_000})
    fast = await h.new_chat()
    smart = await smart_chat(h)

    assert (await h.say(fast.id, "hello")).usage.day.used == 120
    with pytest.raises(AiLimitReachedError) as caught:
        await h.say(smart.id, "hello")

    assert caught.value.params["scope"] == "day"
    assert len(h.llm.requests) == 1
    assert h.store.chat_messages(smart.id) == []


async def test_a_summary_is_its_own_task_with_its_own_model_and_weight(
    h: AiHarness,
) -> None:
    """AI-9: the summary of a smart chat runs as CHAT_SUMMARY, not as the smart tier."""
    chat = await smart_chat(h)
    h.store.messages[chat.id] = [
        ChatMessage(
            id=new_id(),
            chat_id=chat.id,
            seq=seq,
            role=MessageRole.USER if seq % 2 else MessageRole.ASSISTANT,
            content=MessageContent(text=f"message {seq}"),
            created_at=h.clock.now(),
        )
        for seq in range(1, 32)
    ]

    result = await h.say(chat.id, "and now?")

    summary_request, answer_request = h.llm.requests
    assert summary_request["tools"] == [] and answer_request["tools"] != []
    assert summary_request["model"] == h.settings.ai_profile(AiTask.CHAT_SUMMARY).model
    assert (
        answer_request["model"]
        == h.settings.ai_profile(AiTask.STUDENT_CHAT_SMART).model
    )
    assert result.usage.session.used == 120 * 4 + 120  # the answer x4, the summary x1


async def test_the_administration_assistant_ignores_the_tier(h: AiHarness) -> None:
    """AI-13: one model, weight 1; the stored tier is fast."""
    chat = await h.services.create_chat.execute(
        actor=h.admin, assistant=Assistant.ADMIN, tier=ChatTier.SMART
    )

    result = await h.say(chat.id, "hello", actor=h.admin)

    stored = h.store.chats[chat.id]
    assert (chat.tier, stored.tier) == ("fast", ChatTier.FAST)
    admin_model = h.settings.ai_profile(AiTask.ADMIN_CHAT).model
    assert stored.model == admin_model
    assert h.llm.requests[0]["model"] == admin_model
    assert result.usage.session.used == 120
