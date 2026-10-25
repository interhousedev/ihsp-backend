"""The teacher sent the topic: save it right away (BOT-17)."""

from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.html import escape
from app.shared.actor import Actor
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

TOPIC_MAX_CHARS = 300


async def receive_topic_text(
    message: Message,
    state: FSMContext,
    actor: Actor,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Store the topic on the lesson and end the input."""
    topic = (message.text or "").strip()
    if len(topic) > TOPIC_MAX_CHARS:
        await message.answer(i18n("bot-topic-too-long", limit=TOPIC_MAX_CHARS))
        return
    data = await state.get_data()
    await services.classwork.set_topic(b64_to_uuid(data["lesson"]), actor, topic)
    await state.clear()
    await message.answer(i18n("bot-topic-saved", topic=escape(topic)))
