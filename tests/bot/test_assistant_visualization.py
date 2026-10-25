"""The "See visualization" button under answers with valid OpenUI blocks."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.bot.assistant.deliver import AiVizCb
from app.modules.links.domain.errors import ShareNotAllowedError
from app.shared.actor import Actor
from tests.bot.support.fake_ai import FakeAi, done
from tests.bot.support.fakes import TEACHER_TG
from tests.bot.support.harness import Harness

import pytest
from aiogram.methods import EditMessageReplyMarkup

BLOCK = (
    "```openui\n"
    "root = Stack([t])\n"
    't = Table(["Day", "Mark"], [["Mon", 5], ["Tue", 4]])\n'
    "```\n"
)
BAD = "```openui\nroot = Nope(1)\n```\n"


class FakeShareMessage:
    """Records the shares the bot asks for."""

    def __init__(self) -> None:
        """No shares yet."""
        self.calls: list[dict[str, Any]] = []
        self.refuse = False

    async def execute(self, actor: Actor, *, chat_id: UUID, seq: int) -> Any:
        """Return a share view with a 7-day expiry."""
        if self.refuse:
            raise ShareNotAllowedError()
        self.calls.append({"user": actor.user_id, "chat_id": chat_id, "seq": seq})
        now = datetime(2026, 10, 26, tzinfo=UTC)
        link = SimpleNamespace(created_at=now, expires_at=now + timedelta(days=7))
        return SimpleNamespace(link=link, url="https://s.ihsu.uz/ai/m-abc")


@pytest.fixture
def ai(harness: Harness) -> FakeAi:
    """The scripted assistant."""
    fake = FakeAi()
    harness.world.container.ai = fake
    return fake


@pytest.fixture
def shares(harness: Harness) -> FakeShareMessage:
    """The links use case behind the button."""
    fake = FakeShareMessage()
    harness.world.container.links.share_message = fake
    return fake


def _viz(harness: Harness) -> list[str]:
    prefix = AiVizCb.__prefix__ + ":"
    return [c for c in harness.last_callbacks() if c.startswith(prefix)]


async def test_button_only_with_valid_blocks(
    harness: Harness, ai: FakeAi, shares: FakeShareMessage
) -> None:
    ai.play([done(f"Marks:\n{BLOCK}")], [done("Plain.")], [done(f"Bad\n{BAD}")])

    await harness.send("marks")
    assert "bot-ai-visualization" in harness.last_labels()
    data = _viz(harness)
    assert len(data) == 1 and len(data[0].encode()) <= 64
    assert shares.calls == []  # lazy: nothing shared before the press

    await harness.send("plain")
    assert "bot-ai-visualization" not in str(harness.last().reply_markup)
    await harness.send("bad")
    assert "bot-ai-visualization" not in str(harness.last().reply_markup)


async def test_press_creates_share_and_links_it(
    harness: Harness, ai: FakeAi, shares: FakeShareMessage
) -> None:
    ai.play([done(f"Marks:\n{BLOCK}")])
    await harness.send("marks")
    data = _viz(harness)[0]

    await harness.press(data)
    await harness.press(data)

    assert len(shares.calls) == 1  # the second press reuses the URL
    assert shares.calls[0]["chat_id"] == ai.chats[0]
    assert shares.calls[0]["seq"] == 2
    edits = harness.session.calls(EditMessageReplyMarkup)
    urls = [b.url for row in edits[-1].reply_markup.inline_keyboard for b in row]
    assert "https://s.ihsu.uz/ai/m-abc" in urls


async def test_only_the_owner_can_press(
    harness: Harness, ai: FakeAi, shares: FakeShareMessage
) -> None:
    ai.play([done(f"Marks:\n{BLOCK}")])
    await harness.send("marks")

    await harness.press(_viz(harness)[0], user_id=TEACHER_TG)

    assert shares.calls == []
    assert harness.toasts[-1].text == "bot-stale-button"


async def test_refused_share_tells_the_user(
    harness: Harness, ai: FakeAi, shares: FakeShareMessage
) -> None:
    ai.play([done(f"Marks:\n{BLOCK}")])
    await harness.send("marks")
    shares.refuse = True

    await harness.press(_viz(harness)[0])

    assert harness.toasts[-1].text == "bot-ai-visualization-failed"
    assert harness.session.calls(EditMessageReplyMarkup) == []
