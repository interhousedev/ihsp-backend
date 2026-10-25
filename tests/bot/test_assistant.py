"""Free text from a linked user is a request to the web chat assistant."""

from app.modules.ai.domain.errors import AiLimitReachedError, ChatNotFoundError
from app.shared.actor import Role
from tests.bot.support.fake_ai import FakeAi, call_view, delta, done, round_end
from tests.bot.support.fakes import STUDENT_TG, TEACHER_TG, make_user
from tests.bot.support.harness import Harness

import pytest
from aiogram.methods import SendChatAction, SendMessage, SendMessageDraft

ADMIN_TG = 3003


@pytest.fixture
def ai(harness: Harness) -> FakeAi:
    """The scripted assistant, installed in the container."""
    fake = FakeAi()
    harness.world.container.ai = fake
    return fake


def _texts(harness: Harness) -> list[str]:
    return [m.text or "" for m in harness.session.calls(SendMessage)]


async def test_free_text_is_answered_by_the_assistant(
    harness: Harness, ai: FakeAi
) -> None:
    ai.play([delta("The answer "), delta("is 42."), done("The answer is 42.")])

    await harness.send("What is the answer?")

    assert ai.sent[0]["text"] == "What is the answer?"
    assert harness.session.calls(SendChatAction)
    assert "The answer is 42." in _texts(harness)[-1]
    # Only the answer: no status line, no placeholder, no empty draft.
    assert not any("thinking" in t.lower() for t in _texts(harness))
    assert all((d.text or "").strip() for d in harness.session.calls(SendMessageDraft))


async def test_progress_notes_before_tool_calls_are_not_shown(
    harness: Harness, ai: FakeAi
) -> None:
    ai.play(
        [
            delta("Let me look at your schedule."),
            round_end("Let me look at your schedule."),
            delta("Physics at 9:00."),
            done("Physics at 9:00."),
        ]
    )

    await harness.send("What do I have today?")

    texts = _texts(harness)
    assert len(texts) == 1
    assert "Physics at 9:00." in texts[0]
    assert "Let me look" not in texts[0]


async def test_one_conversation_until_new(harness: Harness, ai: FakeAi) -> None:
    await harness.send("first")
    await harness.send("second")
    assert len(ai.chats) == 1
    assert ai.sent[0]["chat_id"] == ai.sent[1]["chat_id"]

    await harness.send("/new")
    assert "bot-ai-new-chat" in harness.last_text()
    await harness.send("third")

    assert len(ai.chats) == 2
    assert ai.sent[2]["chat_id"] == ai.chats[1]


async def test_a_lost_chat_is_replaced(harness: Harness, ai: FakeAi) -> None:
    await harness.send("first")
    ai.play(ChatNotFoundError(), [done("fresh")])

    await harness.send("second")

    assert len(ai.chats) == 2
    assert "fresh" in _texts(harness)[-1]


async def test_a_refusal_is_told_to_the_user(harness: Harness, ai: FakeAi) -> None:
    ai.play(AiLimitReachedError(params={"limit": 5}))

    await harness.send("hello")

    assert AiLimitReachedError.message_key in harness.last_text()


async def test_studio_generation_waits_for_approval(
    harness: Harness, ai: FakeAi
) -> None:
    ai.play(
        [done("I can make a quiz.", calls=[call_view("toolu_quiz")])],
        [delta("Queued."), done("Queued. The quiz will be ready soon.")],
    )

    await harness.send("Make me a quiz on optics")

    assert "Create a quiz" in harness.last_text()
    labels = harness.last_labels()
    assert labels == ["bot-ai-approve", "bot-ai-cancel"]
    approve = harness.last_callbacks()[0]
    assert ai.decided == []

    await harness.press(approve)

    assert ai.decided == [{"chat_id": ai.chats[0], "call_id": "toolu_quiz", "ok": True}]
    assert "The quiz will be ready soon." in _texts(harness)[-1]


async def test_cancel_rejects_the_proposal(harness: Harness, ai: FakeAi) -> None:
    ai.play([done("Shall I?", calls=[call_view("toolu_x")])], [done("Cancelled.")])
    await harness.send("make slides")

    await harness.press(harness.last_callbacks()[1])

    assert ai.decided[0]["ok"] is False


async def test_an_old_approval_button_is_stale(harness: Harness, ai: FakeAi) -> None:
    await harness.press("ai:unknowntoken:1")

    assert ai.decided == []
    assert harness.toasts[-1].text == "bot-stale-button"


# - - - Regression: /today must never reach the assistant - - -


async def test_today_is_a_command_not_an_ai_request(
    harness: Harness, ai: FakeAi
) -> None:
    await harness.send("/today")

    assert ai.sent == []
    assert harness.session.calls(SendMessageDraft) == []
    assert "bot-today-empty" in harness.last_text()


async def test_commands_of_users_without_a_today_screen_skip_the_assistant(
    harness: Harness, ai: FakeAi
) -> None:
    """An administrator has no Today screen: /today falls to the hint, not the AI."""
    harness.world.directory.link(ADMIN_TG, make_user(Role.ADMIN, login="admin"))

    await harness.send("/today", user_id=ADMIN_TG)
    await harness.send("/unknown", user_id=ADMIN_TG)

    assert ai.sent == []
    assert harness.session.calls(SendMessageDraft) == []
    assert "bot-hint-unexpected" in harness.last_text()


async def test_without_the_ai_module_the_hint_stays(harness: Harness) -> None:
    await harness.send("hello", user_id=STUDENT_TG)

    assert "bot-hint-unexpected" in harness.last_text()


async def test_approval_tokens_are_single_use_and_bound_to_the_user(
    harness: Harness, ai: FakeAi
) -> None:
    ai.play([done("Shall I?", calls=[call_view("toolu_y")])], [done("Done.")])
    await harness.send("make a quiz")
    approve = harness.last_callbacks()[0]

    await harness.press(approve, user_id=TEACHER_TG)  # someone else's button
    assert ai.decided == []

    await harness.press(approve)
    await harness.press(approve)  # spent
    assert len(ai.decided) == 1
    assert harness.toasts[-1].text == "bot-stale-button"


async def test_model_buttons_never_carry_callback_data(
    harness: Harness, ai: FakeAi
) -> None:
    from app.interfaces.bot.assistant.render import _chunk
    from app.interfaces.bot.richtext import ButtonSpec, TelegramChunk

    chunk = _chunk(
        TelegramChunk(
            "x",
            buttons=(
                ButtonSpec("Open", url="https://ihsu.uz"),
                ButtonSpec("Approve", callback_data="ai:forged:1"),
            ),
        )
    )

    assert [[b.url for b in row] for row in chunk.rows] == [["https://ihsu.uz"]]


async def test_a_teacher_without_an_assistant_gets_a_hint(
    harness: Harness, ai: FakeAi
) -> None:
    await harness.send("hello", user_id=TEACHER_TG)

    assert ai.sent == [] and ai.chats == []
    assert harness.last_text() == "bot-ai-no-assistant"
