"""Use cases: which Telegram topic carries which AI chat (private-chat topics)."""

from uuid import UUID

from app.modules.ai.domain.telegram_topic import TelegramTopic
from app.modules.ai.ports.unit_of_work import UowFactory


class TelegramTopics:
    """Reads and writes the 1:1 links between AI chats and topics."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Bind the unit of work factory."""
        self._uow = uow_factory

    async def link(self, topic: TelegramTopic) -> None:
        """Persist the link of a chat and its topic."""
        async with self._uow() as uow:
            await uow.telegram_topics.add(topic)
            await uow.commit()

    async def of_chat(self, chat_id: UUID) -> TelegramTopic | None:
        """The topic of an AI chat, None when it has none yet."""
        async with self._uow() as uow:
            return await uow.telegram_topics.by_chat(chat_id)

    async def of_thread(
        self, telegram_chat_id: int, message_thread_id: int
    ) -> TelegramTopic | None:
        """The link of a topic, None when it is not an AI chat yet."""
        async with self._uow() as uow:
            return await uow.telegram_topics.by_thread(
                telegram_chat_id, message_thread_id
            )

    async def unlink(self, chat_id: UUID) -> None:
        """Forget the link of an AI chat."""
        async with self._uow() as uow:
            await uow.telegram_topics.delete_by_chat(chat_id)
            await uow.commit()
