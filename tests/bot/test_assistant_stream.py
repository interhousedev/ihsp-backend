"""The live answer: one rendering path for drafts and finals, and no parse errors."""

import re

from app.interfaces.bot.assistant.render import render_draft, render_final
from app.interfaces.bot.assistant.stream import AnswerStream
from tests.bot.support.recording_bot import RecordingSession, make_bot, session_of

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage, SendMessageDraft

SAMPLE = (
    "# Plan\n\n**Bold** and *italic* with `code` and [a link](https://iht.uz).\n\n"
    "- first item\n- second item\n\n"
    "| Day | Mark |\n| --- | --- |\n| Mon | 5 |\n\n"
    "```python\nprint('x')\n```\n\n"
    "Formula: $$\\frac{1}{2}$$ and 1 < 2 & 3 > 2."
)
ALLOWED = {"b", "i", "s", "code", "pre", "a", "blockquote"}
TAG = re.compile(r"<(/?)([a-zA-Z]+)[^>]*>")


def _balanced(html: str) -> bool:
    stack: list[str] = []
    for closing, name in TAG.findall(html):
        if name not in ALLOWED:
            return False
        if not closing:
            stack.append(name)
        elif not stack or stack.pop() != name:
            return False
    return not stack


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message=message)


def test_a_draft_shows_exactly_the_last_final_message() -> None:
    final = render_final(SAMPLE)
    assert len(final) == 1
    assert render_draft(SAMPLE) == final[-1].html


def test_a_long_draft_shows_the_last_final_chunk() -> None:
    long_text = (SAMPLE + "\n\n") * 80
    final = render_final(long_text)
    assert len(final) > 1
    assert render_draft(long_text) == final[-1].html


def test_every_partial_answer_is_well_formed_html() -> None:
    for end in range(1, len(SAMPLE) + 1):
        draft = render_draft(SAMPLE[:end])
        assert _balanced(draft), (end, draft)
        assert "<" not in re.sub(TAG, "", draft).replace("&lt;", "")


async def test_a_draft_error_from_telegram_falls_back_to_plain_text() -> None:
    bot: Bot = make_bot()
    session: RecordingSession = session_of(bot)
    session.queue(
        SendMessageDraft,
        _bad_request("Bad Request: can't parse entities: unsupported start tag"),
    )
    stream = AnswerStream(bot, 1, 7, drafts=True)

    await stream.update("**Hello** <world>")

    sent = session.calls(SendMessage)
    assert sent, "the answer must still be shown"
    assert sent[-1].text == "Hello &lt;world&gt;"


async def test_a_final_html_error_resends_plain_text() -> None:
    bot: Bot = make_bot()
    session: RecordingSession = session_of(bot)
    session.queue(SendMessage, _bad_request("Bad Request: can't find end tag"))
    stream = AnswerStream(bot, 1, 7, drafts=False)

    await stream.finish([render_final("**Bold** a < b")[0]], [])

    sent = session.calls(SendMessage)
    assert len(sent) == 2
    assert sent[1].text == "Bold a &lt; b"
