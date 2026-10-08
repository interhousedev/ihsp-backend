"""AI-8, AI-9, UF-WEB-21: session window and daily token budgets."""

from datetime import UTC, datetime

from app.modules.ai.application.views import TurnStatus
from app.modules.ai.domain.errors import AiLimitReachedError, WrongAssistantError
from tests.ai.conftest import HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest


async def test_the_first_message_opens_a_five_hour_window(
    make_harness: HarnessFactory,
) -> None:
    """AI-8: the window starts with the first usage and lasts ai_session_hours."""
    h = make_harness()
    chat = await h.new_chat()
    before = await h.services.get_usage.execute(actor=h.student, assistant=None)
    assert before.session.resets_at is None and before.session.used == 0

    await h.say(chat.id, "hello")

    after = await h.services.get_usage.execute(actor=h.student, assistant=None)
    assert after.session.resets_at == datetime(2026, 10, 6, 14, 0, tzinfo=UTC)
    assert after.session.used == 120
    assert after.session.limit == 200_000 and after.day.limit == 600_000


async def test_the_session_budget_resets_after_five_hours(
    make_harness: HarnessFactory,
) -> None:
    """AI-8: a request over the session limit stops the turn until a new window."""
    h = make_harness(limits={"ai_session_tokens_student": 12_000})
    chat = await h.new_chat()
    h.llm.push(tool_reply(("get_my_subjects", {}), tokens=9_000))

    stopped = await h.say(chat.id, "first")

    assert stopped.status is TurnStatus.LIMIT_REACHED
    assert stopped.usage.session.used == 9_020
    with pytest.raises(AiLimitReachedError) as caught:
        await h.say(chat.id, "second")
    assert caught.value.params["scope"] == "session"
    assert caught.value.status == 429

    h.clock.advance(hours=5, minutes=1)
    h.llm.push(text_reply("hello again"))
    resumed = await h.say(chat.id, "third")

    assert resumed.status is TurnStatus.DONE
    assert resumed.usage.session.used == 120  # a fresh window


async def test_the_daily_limit_blocks_until_tashkent_midnight(
    make_harness: HarnessFactory,
) -> None:
    """AI-8: the day resets at 00:00 Tashkent; the error says when."""
    h = make_harness(limits={"ai_daily_tokens_student": 8_000})
    chat = await h.new_chat()
    h.llm.push(text_reply("a", tokens=3_000))
    await h.say(chat.id, "one")

    with pytest.raises(AiLimitReachedError) as caught:
        await h.say(chat.id, "two")

    assert caught.value.params["scope"] == "day"
    midnight = datetime(2026, 10, 6, 19, 0, tzinfo=UTC).isoformat()
    assert caught.value.params["resets_at"] == midnight
    assert len(h.llm.requests) == 1
    detail = await h.services.get_chat.execute(actor=h.student, chat_id=chat.id)
    assert [m.text for m in detail.messages] == ["one", "a"]  # "two" was not stored

    h.clock.advance(hours=10)  # 19:00 UTC = 00:00 in Tashkent
    h.llm.push(text_reply("back"))
    assert (await h.say(chat.id, "three")).status is TurnStatus.DONE


async def test_admin_assistant_has_its_own_limits(make_harness: HarnessFactory) -> None:
    """AI-8: limits are set per role."""
    h = make_harness()

    usage = await h.services.get_usage.execute(actor=h.admin, assistant=None)

    assert (usage.session.limit, usage.day.limit) == (400_000, 1_200_000)


async def test_usage_of_the_other_assistant_is_forbidden(
    make_harness: HarnessFactory,
) -> None:
    """AI-1: a student cannot ask for the Administration usage."""
    from app.modules.ai.domain.assistant import Assistant

    h = make_harness()

    with pytest.raises(WrongAssistantError):
        await h.services.get_usage.execute(actor=h.student, assistant=Assistant.ADMIN)
