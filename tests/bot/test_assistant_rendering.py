"""A streamed answer with a table: the same rich rendering in the draft and the end."""

from tests.bot.support.fake_ai import FakeAi, delta, done
from tests.bot.support.harness import Harness

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage, SendMessageDraft

ANSWER = (
    "**Your marks**\n\n"
    "| Subject | Mark |\n| --- | --- |\n| Physics | 5 |\n| Chemistry | 4 |\n\n"
    "Ask me about *any* of them."
)


@pytest.fixture
def ai(harness: Harness) -> FakeAi:
    """The scripted assistant."""
    fake = FakeAi()
    harness.world.container.ai = fake
    return fake


def _balanced(text: str) -> bool:
    return text.count("<pre>") == text.count("</pre>")


async def test_a_table_answer_is_rich_while_streaming_and_at_the_end(
    harness: Harness, ai: FakeAi
) -> None:
    ai.play([delta(ANSWER[:40]), delta(ANSWER[40:]), done(ANSWER)])

    await harness.send("show my marks")

    drafts = [d.text or "" for d in harness.session.calls(SendMessageDraft)]
    assert drafts, "a private chat streams a draft"
    assert all(_balanced(text) for text in drafts)
    final = harness.last_text()
    assert "<b>Your marks</b>" in final
    assert "<pre>Subject" in final and "Physics    5" in final
    assert "<i>any</i>" in final
    assert "|" not in final


async def test_a_refused_draft_markup_still_delivers_the_answer(
    harness: Harness, ai: FakeAi
) -> None:
    harness.session.queue(
        SendMessageDraft,
        TelegramBadRequest(
            method=SendMessageDraft(chat_id=1, draft_id=1, text="x"),
            message="Bad Request: can't parse entities: unsupported start tag",
        ),
    )
    ai.play([delta(ANSWER), done(ANSWER)])

    await harness.send("show my marks")

    texts = [m.text or "" for m in harness.session.calls(SendMessage)]
    assert any("Physics" in text for text in texts)
    assert all(_balanced(text) for text in texts)


async def test_the_bot_turn_asks_for_the_telegram_formatting(
    harness: Harness, ai: FakeAi
) -> None:
    ai.play([done("ok")])

    await harness.send("show my marks")

    assert ai.sent[0]["surface"] == "telegram"
