"""OpenUI in the bot's answers: blocks close the message; widgets stay off by default.

The model shows a block with the `show_ui_block` tool; the bot appends its Markdown
form to the end of the answer. Tables and rich text of the answer itself keep their
Telegram rendering. No `sendWidget` leaves the bot unless `IHSP_BOT__WIDGETS_ENABLED`.
"""

from typing import Any

from app.interfaces.bot.assistant.service import bot_assistant
from app.interfaces.bot.bot import allowed_updates, build_dispatcher
from app.interfaces.bot.widgets.methods import SendWidget
from app.interfaces.bot.widgets.queries import WidgetQueryMiddleware
from app.settings import BotSettings
from tests.bot.support.fake_ai import FakeAi, call_view, delta, done, round_end
from tests.bot.support.fakes import World
from tests.bot.support.harness import Harness

import pytest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage

CHART = 'root = Stack([chart])\nchart = BarChart(["Mon", "Tue"], [3, 5], "Marks")\n'
TABLE = 'root = Stack([t])\nt = Table(["Term", "Fee"], [["1", 5], ["2", 6]])\n'
BROKEN = 'root = Stack([chart])\nchart = BarChart(["Mon", "Tue"])\n'
MARKDOWN_TABLE = "| Subject | Mark |\n| --- | --- |\n| Physics | 5 |\n| Algebra | 4 |"


@pytest.fixture
def ai(harness: Harness) -> FakeAi:
    """The scripted assistant, installed in the container."""
    fake = FakeAi()
    harness.world.container.ai = fake
    return fake


def _block(source: str, call_id: str = "toolu_1") -> Any:
    return call_view(call_id, status="done", tool="show_ui_block", ui_block=source)


def _texts(harness: Harness) -> list[str]:
    return [m.text or "" for m in harness.session.calls(SendMessage)]


def _fenced(source: str) -> str:
    return f"```openui\n{source}```\n"


async def test_markdown_table_and_bold_render_and_the_block_comes_last(
    harness: Harness, ai: FakeAi
) -> None:
    """The answer's own table is monospace; the tool block follows all the text."""
    body = f"**Your marks**\n\n{MARKDOWN_TABLE}\n\nKeep going."
    ai.play([delta(body), done(body, calls=[_block(CHART)])])

    await harness.send("marks")

    (text,) = _texts(harness)
    assert "<b>Your marks</b>" in text
    assert "<pre>" in text and "Physics" in text and "| ---" not in text
    assert "```" not in text and "BarChart" not in text
    assert text.index("Keep going.") < text.index("Mon")


async def test_several_blocks_keep_their_order_at_the_end(
    harness: Harness, ai: FakeAi
) -> None:
    calls = [_block(CHART, "toolu_1"), _block(TABLE, "toolu_2")]
    ai.play([delta("Two views."), done("Two views.", calls=calls)])

    await harness.send("show both")

    (text,) = _texts(harness)
    assert text.index("Two views.") < text.index("Mon") < text.index("Fee")


async def test_blocks_of_earlier_rounds_are_appended_after_the_final_text(
    harness: Harness, ai: FakeAi
) -> None:
    """The tool runs in a round before the answer; its block still closes it."""
    note = "Let me draw it."
    script = [delta(note), round_end(note), delta("Done."), done("Done.")]
    first = script[-1].result.new_messages[0]  # type: ignore[union-attr]
    fields = {**vars(first), "text": note, "tool_calls": [_block(CHART)]}
    earlier = type(first)(**fields)
    script[-1].result.new_messages.insert(0, earlier)  # type: ignore[union-attr]
    ai.play(script)

    await harness.send("draw")

    (text,) = _texts(harness)
    assert note not in text
    assert text.index("Done.") < text.index("Mon")


async def test_a_block_without_text_is_the_whole_message(
    harness: Harness, ai: FakeAi
) -> None:
    ai.play([done("", calls=[_block(CHART)])])

    await harness.send("chart only")

    (text,) = _texts(harness)
    assert "Mon" in text and "bot-ai-empty" not in text


async def test_a_block_written_in_the_text_moves_to_the_end(
    harness: Harness, ai: FakeAi
) -> None:
    """A fenced block the model wrote anyway is shown after the text around it."""
    body = f"Before.\n\n{_fenced(CHART)}\nAfter."
    ai.play([delta(body), done(body)])

    await harness.send("inline")

    (text,) = _texts(harness)
    assert text.index("Before.") < text.index("After.") < text.index("Mon")
    assert "```" not in text and "BarChart" not in text


async def test_a_broken_block_in_the_text_is_dropped(
    harness: Harness, ai: FakeAi
) -> None:
    body = f"Before.\n\n{_fenced(BROKEN)}\nAfter."
    ai.play([delta(body), done(body)])

    await harness.send("broken")

    (text,) = _texts(harness)
    assert "Before." in text and "After." in text
    assert "BarChart" not in text and "Mon" not in text


async def test_a_long_answer_is_split_and_the_block_is_in_the_last_part(
    harness: Harness, ai: FakeAi
) -> None:
    body = "\n\n".join(f"Paragraph {i}. " + "word " * 120 for i in range(12))
    ai.play([delta(body), done(body, calls=[_block(CHART)])])

    await harness.send("long")

    texts = _texts(harness)
    assert len(texts) > 1
    assert all(len(t) <= 4096 for t in texts)
    assert "Mon" in texts[-1] and not any("Mon" in t for t in texts[:-1])


async def test_widgets_off_never_sends_a_widget(harness: Harness, ai: FakeAi) -> None:
    """The default: tool blocks and fenced blocks are text, never `sendWidget`."""
    assert harness.world.container.settings.bot.widgets_enabled is False
    body = f"Marks.\n\n{_fenced(TABLE)}"
    ai.play([delta(body), done(body, calls=[_block(CHART)])])

    await harness.send("marks")

    assert not harness.session.calls(SendWidget)
    (text,) = _texts(harness)
    assert "Fee" in text and "Mon" in text


async def test_widgets_on_sends_the_tool_block_as_a_widget(
    harness: Harness, ai: FakeAi
) -> None:
    """The flag still works: the code stays, switched off by default."""
    assistant = bot_assistant(harness.world.container)
    assert assistant is not None
    assistant.widgets = True
    ai.play([delta("Marks."), done("Marks.", calls=[_block(CHART)])])

    await harness.send("marks")

    assert len(harness.session.calls(SendWidget)) == 1
    (text,) = _texts(harness)
    assert "Marks." in text and "Mon" not in text


def test_the_flag_is_off_by_default() -> None:
    assert BotSettings().widgets_enabled is False


def test_widgets_off_means_no_widget_updates_and_no_middleware(world: World) -> None:
    settings = world.container.settings
    assert settings.bot.widgets_enabled is False
    dispatcher = build_dispatcher(world.container, MemoryStorage())

    asked = allowed_updates(dispatcher, settings)

    assert "widget_query" not in asked and "shared_widget_query" not in asked
    assert not any(
        isinstance(m, WidgetQueryMiddleware) for m in dispatcher.update.outer_middleware
    )
