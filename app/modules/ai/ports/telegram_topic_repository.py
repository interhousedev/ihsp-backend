"""Port: the links between AI chats and Telegram topics."""

from typing import Protocol
from uuid import UUID

from app.modules.ai.domain.telegram_topic import TelegramTopic


class TelegramTopicRepository(Protocol):
    """One topic per AI chat; one AI chat per (Telegram chat, thread)."""

    async def add(self, topic: TelegramTopic) -> None:
        """Store the link (replaces an older link of the same AI chat)."""
        ...

    async def by_chat(self, chat_id: UUID) -> TelegramTopic | None:
        """The topic of an AI chat."""
        ...

    async def by_thread(
        self, telegram_chat_id: int, message_thread_id: int
    ) -> TelegramTopic | None:
        """The link of a topic."""
        ...

    async def delete_by_chat(self, chat_id: UUID) -> None:
        """Forget the link of an AI chat."""
        ...
