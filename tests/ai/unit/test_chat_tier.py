"""AI-1, AI-8, AI-13: the fast and smart tiers of a student chat."""

from datetime import UTC, datetime

from app.modules.ai.application.budget import (
    BudgetService,
    SmartUsagePart,
)
from app.modules.ai.application.views import ChatItemView
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import (
    ChatMessage,
    ChatTier,
    MessageContent,
    MessageRole,
)
from app.modules.ai.domain.errors import (
    AiLimitReachedError,
    AiSmartLimitReachedError,
    AttachmentInvalidError,
)
from app.settings import Settings
from app.settings_ai import AiTaskSettings
from app.shared.actor import Actor, Role
from app.shared.ai_tasks import AiTask
from app.shared.ids import new_id
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply
from tests.fakes.ai.stores import InMemoryBudgetStore
from tests.fakes.clock import FixedClock

import pytest
from pydantic import ValidationError

# Monday 00:00 in Tashkent (UTC+5): the next week starts here.
NEXT_WEEK = datetime(2026, 10, 11, 19, 0, tzinfo=UTC)


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
    assert smart == "google/gemini-3.8-flash" and chat.tier == "smart"
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
    """AI-8: 120 real tokens cost 8 x 120 of the budget; the message keeps 100/20."""
    chat = await smart_chat(h)

    result = await h.say(chat.id, "hello")

    assert result.usage.session.used == 960 and result.usage.day.used == 960
    message = h.store.chat_messages(chat.id)[-1]
    assert (message.tokens_in, message.tokens_out) == (100, 20)


async def test_every_step_of_a_smart_turn_is_weighted(h: AiHarness) -> None:
    """AI-9: tool loops are counted per request, each times the weight."""
    chat = await smart_chat(h)
    h.llm.push(tool_reply(("get_my_subjects", {})), text_reply("done"))

    result = await h.say(chat.id, "my subjects")

    assert result.usage.session.used == (120 + 120) * 8


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
    assert result.usage.session.used == 120 * 8 + 120  # the answer x8, the summary x1


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


async def test_the_default_weekly_limit_is_three_smart_messages(
    h: AiHarness,
) -> None:
    """AI-13: the setting's default is 3; the fourth smart message of a week is refused
    before anything is stored or sent to the model."""
    limit = h.settings.limits.ai_smart_requests_per_week_student
    assert limit == 3
    chat = await smart_chat(h)
    for number in range(limit):
        await h.say(chat.id, f"message {number}")
    calls, stored = len(h.llm.requests), len(h.store.chat_messages(chat.id))

    with pytest.raises(AiSmartLimitReachedError) as caught:
        await h.say(chat.id, "one too many")

    assert (caught.value.code, caught.value.status) == ("ai/smart-weekly-limit", 429)
    assert caught.value.params == {
        "limit": "3",
        "date": "12.10.2026",
        "resets_at": NEXT_WEEK.isoformat(),
    }
    assert len(h.llm.requests) == calls
    assert len(h.store.chat_messages(chat.id)) == stored


async def test_the_smart_count_resets_on_monday_in_tashkent(
    make_harness: HarnessFactory,
) -> None:
    """AI-13: the week ends at Monday 00:00 Tashkent (19:00 UTC on Sunday)."""
    h = make_harness(limits={"ai_smart_requests_per_week_student": 1})
    chat = await smart_chat(h)
    await h.say(chat.id, "saturday")

    h.clock.set(datetime(2026, 10, 11, 18, 59, tzinfo=UTC))  # Sunday 23:59 Tashkent
    with pytest.raises(AiSmartLimitReachedError):
        await h.say(chat.id, "still the same week")

    h.clock.set(NEXT_WEEK)  # Monday 00:00 Tashkent
    result = await h.say(chat.id, "new week")

    assert result.usage.smart == SmartUsagePart(
        used=1,
        limit=1,
        remaining=0,
        resets_at=datetime(2026, 10, 18, 19, 0, tzinfo=UTC),
    )


async def test_the_usage_shows_the_smart_requests_left(h: AiHarness) -> None:
    """AI-13: smart requests left and their reset, before and after a message."""
    chat = await smart_chat(h)

    before = await h.services.get_usage.execute(actor=h.student, assistant=None)
    result = await h.say(chat.id, "hello")

    assert before.smart == SmartUsagePart(0, 3, 3, NEXT_WEEK)
    assert result.usage.smart == SmartUsagePart(1, 3, 2, NEXT_WEEK)


async def test_fast_messages_do_not_use_up_smart_requests(h: AiHarness) -> None:
    """AI-13: the fast tier has no weekly count; only smart messages are counted."""
    smart = await smart_chat(h)
    fast = await h.new_chat()
    for number in range(4):
        await h.say(fast.id, f"fast {number}")

    usage = await h.services.get_usage.execute(actor=h.student, assistant=None)
    assert usage.smart == SmartUsagePart(0, 3, 3, NEXT_WEEK)
    await h.say(smart.id, "still allowed")


async def test_a_smart_message_refused_before_storing_uses_no_request(
    h: AiHarness,
) -> None:
    """AI-13: a message that fails its checks (here an unknown file) is not counted."""
    chat = await smart_chat(h)

    with pytest.raises(AttachmentInvalidError):
        await h.say(chat.id, "with a file", files=[new_id()])

    usage = await h.services.get_usage.execute(actor=h.student, assistant=None)
    assert usage.smart is not None and usage.smart.used == 0


async def test_a_reserved_request_given_back_counts_again(
    settings: Settings,
) -> None:
    """AI-13: a reservation at the limit is refused and counts nothing; a released one
    frees its place again."""
    budget = BudgetService(InMemoryBudgetStore(), FixedClock(), settings)
    user = new_id()

    for _ in range(2):
        assert await budget.reserve_smart(user, 2) is None
    refused = await budget.reserve_smart(user, 2)
    assert refused is not None and refused.limit == 2
    assert (await budget.smart_usage(user, 2)).used == 2

    await budget.release_smart(user)
    assert await budget.reserve_smart(user, 2) is None


async def test_staff_are_not_limited_but_their_requests_are_counted(
    settings: Settings,
) -> None:
    """AI-13: a teacher or admin has no weekly limit; a student limit of 0 turns the
    smart tier off for students at once."""
    budget = BudgetService(InMemoryBudgetStore(), FixedClock(), settings)
    teacher = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))
    student = Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))
    off = settings.model_copy(
        update={
            "limits": settings.limits.model_copy(
                update={"ai_smart_requests_per_week_student": 0}
            )
        }
    )

    assert await budget.smart_limit(teacher) is None
    for _ in range(5):
        assert await budget.reserve_smart(teacher.user_id, None) is None
    staff_usage = await budget.smart_usage(teacher.user_id, None)
    assert (staff_usage.used, staff_usage.limit, staff_usage.remaining) == (
        5,
        None,
        None,
    )

    off_budget = BudgetService(InMemoryBudgetStore(), FixedClock(), off)
    assert await off_budget.smart_limit(student) == 0
    refused = await off_budget.reserve_smart(student.user_id, 0)
    assert refused is not None and refused.limit == 0


async def test_regenerating_a_smart_answer_counts_a_smart_request(
    make_harness: HarnessFactory,
) -> None:
    """AI-13: "Regenerate" cannot get around the weekly cap: every rerun of a smart
    answer is one more smart request, refused (and nothing removed) at the limit."""
    h = make_harness(limits={"ai_smart_requests_per_week_student": 2})
    chat = await smart_chat(h)
    await h.say(chat.id, "hello")
    kept = [m.text for m in h.store.chat_messages(chat.id)]

    await h.services.regenerate_answer.execute(actor=h.student, chat_id=chat.id)
    usage = await h.services.get_usage.execute(actor=h.student, assistant=None)
    assert usage.smart is not None and usage.smart.used == 2

    calls = len(h.llm.requests)
    with pytest.raises(AiSmartLimitReachedError):
        await h.services.regenerate_answer.execute(actor=h.student, chat_id=chat.id)
    assert len(h.llm.requests) == calls
    assert [m.text for m in h.store.chat_messages(chat.id)][:2] == kept[:2]
    usage = await h.services.get_usage.execute(actor=h.student, assistant=None)
    assert usage.smart is not None and usage.smart.used == 2


async def test_regenerating_a_fast_answer_is_not_counted(h: AiHarness) -> None:
    """AI-13: only the smart tier has the weekly count."""
    chat = await h.new_chat()
    await h.say(chat.id, "hello")

    await h.services.regenerate_answer.execute(actor=h.student, chat_id=chat.id)

    usage = await h.services.get_usage.execute(actor=h.student, assistant=None)
    assert usage.smart == SmartUsagePart(0, 3, 3, NEXT_WEEK)
