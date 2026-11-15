"""Forum topics of the private chat: one topic carries one AI chat (Bot API 9.3).

A message in a topic goes to the AI chat mapped to it, so the history is the same
as on my.iht. Without topics (not enabled in BotFather, groups) every function
returns an empty placement and the bot keeps its single-thread behaviour.
"""

import zlib
from dataclasses import dataclass
from uuid import UUID

from app.interfaces.bot.assistant.service import BotAssistant
from app.modules.ai.domain.assistant import default_assistant
from app.modules.ai.domain.chat import title_from_text
from app.modules.ai.domain.telegram_topic import TelegramTopic
from app.shared.actor import Actor
from app.shared.i18n.core import I18nContext

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, Sticker

TOPIC_NAME_MAX = 128

# Keyword of the chat title -> emojis the topic icon may be (first available wins).
_ICONS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("math", "матем", "algebra", "алгеб", "геометр", "calc"), ("🔥", "💡")),
    (("homework", "домаш", "уроки", "uy ishi"), ("📝", "📚")),
    (("exam", "экзамен", "test", "тест", "imtihon"), ("🎓", "🏆")),
    (("code", "python", "код", "програм", "dastur"), ("💻", "⚡")),
    (("book", "книг", "kitob", "library", "библиот"), ("📚", "📖")),
    (("english", "язык", "til", "language", "английск"), ("💬", "🗣")),
    (("science", "физик", "хими", "biolog", "биолог", "fizika"), ("🔬", "🧪", "🔭")),
    (("music", "музык", "musiqa"), ("🎵", "🎶")),
    (("sport", "спорт"), ("⚽", "🏆")),
)

_stickers: list[Sticker] | None = None


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a turn runs: the AI chat of the topic and the thread to answer in."""

    chat_id: UUID | None = None
    thread_id: int | None = None


def thread_of(message: Message) -> int | None:
    """The topic a message was written in (None in the root chat)."""
    return message.message_thread_id if message.is_topic_message else None


async def topics_enabled(bot: Bot, message: Message) -> bool:
    """True in a private chat of a bot that has topics enabled."""
    if message.chat.type != ChatType.PRIVATE:
        return False
    me = await bot.me()
    return bool(getattr(me, "has_topics_enabled", False))


async def _icon_stickers(bot: Bot) -> list[Sticker]:
    global _stickers  # noqa: PLW0603 - the list is the same for every user
    if _stickers is None:
        try:
            _stickers = list(await bot.get_forum_topic_icon_stickers())
        except TelegramAPIError:
            return []
    return _stickers


def pick_icon(title: str, chat_id: UUID, stickers: list[Sticker]) -> str | None:
    """The topic icon for a chat: by the topic of its title, else a stable pick."""
    if not stickers:
        return None
    lowered = title.lower()
    for keywords, emojis in _ICONS:
        if any(word in lowered for word in keywords):
            for emoji in emojis:
                for sticker in stickers:
                    if sticker.emoji == emoji and sticker.custom_emoji_id:
                        return sticker.custom_emoji_id
    pool = [s for s in stickers if s.custom_emoji_id]
    if not pool:
        return None
    return pool[zlib.crc32(chat_id.bytes) % len(pool)].custom_emoji_id


async def _title(assistant: BotAssistant, actor: Actor, chat_id: UUID) -> str:
    try:
        detail = await assistant.ai.get_chat.execute(actor=actor, chat_id=chat_id)
    except Exception:  # noqa: BLE001 - a missing chat just has no title yet
        return ""
    return str(detail.chat.title or "")


async def _open_topic(
    bot: Bot,
    assistant: BotAssistant,
    actor: Actor,
    message: Message,
    chat_id: UUID,
    name: str,
) -> int | None:
    """Create the topic of a chat and persist the link; None when Telegram refuses."""
    name = (name or "").strip()[:TOPIC_NAME_MAX] or "…"
    icon = pick_icon(name, chat_id, await _icon_stickers(bot))
    try:
        topic = await bot.create_forum_topic(
            message.chat.id, name, icon_custom_emoji_id=icon
        )
    except TelegramAPIError:
        return None
    await assistant.ai.telegram_topics.link(
        TelegramTopic(
            user_id=actor.user_id,
            telegram_chat_id=message.chat.id,
            chat_id=chat_id,
            message_thread_id=topic.message_thread_id,
            title=name,
            icon_custom_emoji_id=icon,
        )
    )
    return int(topic.message_thread_id)


async def place_turn(
    bot: Bot,
    assistant: BotAssistant,
    actor: Actor,
    message: Message,
    text: str,
    i18n: I18nContext,
) -> Placement:
    """Resolve the AI chat and topic for a message (empty when topics are off)."""
    if not await topics_enabled(bot, message):
        return Placement()
    chat = message.chat.id
    thread = thread_of(message)
    if thread is not None:
        mapped = await assistant.ai.telegram_topics.of_thread(chat, thread)
        if mapped is not None:
            return Placement(mapped.chat_id, thread)
        # A topic the user made by hand: it becomes a new AI chat.
        item = await assistant.ai.create_chat.execute(
            actor=actor, assistant=default_assistant(actor)
        )
        await assistant.ai.telegram_topics.link(
            TelegramTopic(
                user_id=actor.user_id,
                telegram_chat_id=chat,
                chat_id=item.id,
                message_thread_id=thread,
            )
        )
        return Placement(item.id, thread)
    chat_id = await assistant.chat_for(actor)
    known = await assistant.ai.telegram_topics.of_chat(chat_id)
    if known is not None and known.telegram_chat_id == chat:
        return Placement(chat_id, known.message_thread_id)
    name = (
        await _title(assistant, actor, chat_id)
        or title_from_text(text)
        or i18n("bot-ai-topic-new")
    )
    opened = await _open_topic(bot, assistant, actor, message, chat_id, name)
    return Placement(chat_id, opened)


async def bind(
    assistant: BotAssistant,
    actor: Actor,
    message: Message,
    placement: Placement,
    chat_id: UUID,
) -> None:
    """Link the chat the turn ran in to the thread (a stale chat was replaced)."""
    if placement.thread_id is None or placement.chat_id == chat_id:
        return
    if await assistant.ai.telegram_topics.of_chat(chat_id) is None:
        await assistant.ai.telegram_topics.link(
            TelegramTopic(
                user_id=actor.user_id,
                telegram_chat_id=message.chat.id,
                chat_id=chat_id,
                message_thread_id=placement.thread_id,
            )
        )


async def sync_title(
    bot: Bot, assistant: BotAssistant, actor: Actor, message: Message, chat_id: UUID
) -> None:
    """Rename the topic when the chat's title changed (first answer, web rename)."""
    topic = await assistant.ai.telegram_topics.of_chat(chat_id)
    if topic is None or topic.telegram_chat_id != message.chat.id:
        return
    title = (await _title(assistant, actor, chat_id))[:TOPIC_NAME_MAX]
    if not title or title == topic.title:
        return
    try:
        await bot.edit_forum_topic(message.chat.id, topic.message_thread_id, name=title)
    except TelegramAPIError:
        return
    topic.title = title
    await assistant.ai.telegram_topics.link(topic)
