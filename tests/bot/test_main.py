"""The bot process entry and the callback fallbacks."""

import asyncio
import contextlib

from app.interfaces.bot.main import run_bot
from tests.bot.support.fakes import STUDENT_TG, World
from tests.bot.support.harness import Harness
from tests.bot.support.recording_bot import inaccessible_callback_update

from aiogram.methods import SendMessage


async def test_fake_mode_idles_without_touching_the_network(world: World) -> None:
    """TELEGRAM__MODE=fake builds everything and waits; tests feed updates."""
    task = asyncio.create_task(run_bot(world.container))
    await asyncio.sleep(0.05)

    assert not task.done()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_a_button_on_an_inaccessible_message_writes_to_the_private_chat(
    harness: Harness,
) -> None:
    """Telegram hides messages older than 48 hours; the answer becomes a new message."""
    update = inaccessible_callback_update(harness.bot, "m:menu")

    await harness.dp.feed_update(harness.bot, update, container=harness.world.container)

    (sent,) = harness.session.calls(SendMessage)
    assert sent.chat_id == STUDENT_TG
    assert (sent.text or "").startswith("bot-menu-greeting")
    assert harness.toasts
