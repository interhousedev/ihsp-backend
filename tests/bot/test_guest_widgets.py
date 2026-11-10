"""Guest answers with OpenUI blocks: widgets, Markdown degrade, Mini App button."""

from collections.abc import AsyncIterator
from typing import Any

from app.interfaces.bot.widgets.methods import SendWidget
from tests.bot.support.harness import Harness

GUEST = 8888
URL = "https://share.example/g-0123456789abcdef0123456789abcdef"
BLOCK = (
    "Fees by term:\n```openui\nroot = Stack([t])\n"
    't = Table(["Term", "Fee"], [["1", 5], ["2", 6]])\n```\n'
)


class StandIn:
    """A guest assistant that answers with a fixed text."""

    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def check_limits(self, telegram_user_id: int) -> None:
        return None

    async def stream_answer(self, question: str, *, locale: str) -> AsyncIterator[str]:
        yield self.answer


class FakeShare:
    """ShareGuestAnswer: records the texts and returns one URL."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def execute(self, *, telegram_user_id: int, text: str) -> str:
        self.texts.append(text)
        return URL


async def _ask(harness: Harness, answer: str, *, widgets: bool) -> FakeShare:
    container: Any = harness.world.container
    container.posts.guest_assistant = StandIn(answer)
    container.settings.bot.widgets_enabled = widgets
    share = FakeShare()
    container.links.share_guest_answer = share
    await harness.send("/start", user_id=GUEST)
    await harness.press("sm:guest", user_id=GUEST)
    await harness.send("Fees as a table", user_id=GUEST)
    return share


def _web_app_urls(harness: Harness) -> list[str]:
    return [
        b.web_app.url
        for request in harness.session.requests
        for row in getattr(
            getattr(request, "reply_markup", None), "inline_keyboard", []
        )
        for b in row
        if b.web_app is not None
    ]


async def test_widgets_on_sends_widget_and_web_app_button(harness: Harness) -> None:
    share = await _ask(harness, BLOCK, widgets=True)
    assert len(harness.session.calls(SendWidget)) == 1
    assert _web_app_urls(harness) == [URL]
    assert share.texts == [BLOCK]
    assert "```" not in "".join(e.text or "" for e in harness.edits)


async def test_widgets_off_degrades_to_markdown_with_button(harness: Harness) -> None:
    await _ask(harness, BLOCK, widgets=False)
    assert not harness.session.calls(SendWidget)
    assert _web_app_urls(harness) == [URL]
    shown = harness.edits[-1].text or ""
    assert "Fees by term" in shown and "Term" in shown and "```" not in shown


async def test_answer_without_blocks_is_unchanged(harness: Harness) -> None:
    share = await _ask(harness, "Plain answer", widgets=True)
    assert not harness.session.calls(SendWidget)
    assert _web_app_urls(harness) == []
    assert share.texts == []
    assert harness.edits[-1].text == "Plain answer"
