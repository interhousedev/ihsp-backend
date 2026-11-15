"""A forum topic of a private Telegram chat that carries one AI chat."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class TelegramTopic:
    """The 1:1 link between an AI chat and a topic (message_thread_id)."""

    user_id: UUID
    telegram_chat_id: int
    chat_id: UUID
    message_thread_id: int
    title: str = ""  # the title last shown as the topic's name
    icon_custom_emoji_id: str | None = None
