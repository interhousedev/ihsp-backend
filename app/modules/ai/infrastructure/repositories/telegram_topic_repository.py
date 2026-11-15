"""SQL repository of the Telegram topic links (ai.telegram_topics)."""

from uuid import UUID

from app.modules.ai.domain.telegram_topic import TelegramTopic
from app.modules.ai.infrastructure.orm.telegram_topic import TelegramTopicRow

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: TelegramTopicRow) -> TelegramTopic:
    return TelegramTopic(
        user_id=row.user_id,
        telegram_chat_id=row.telegram_chat_id,
        chat_id=row.chat_id,
        message_thread_id=row.message_thread_id,
        title=row.title,
        icon_custom_emoji_id=row.icon_custom_emoji_id,
    )


class SqlTelegramTopicRepository:
    """Topic links in `ai.telegram_topics`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def add(self, topic: TelegramTopic) -> None:
        """Insert the link, dropping an older one of the same chat or thread."""
        await self.session.execute(
            delete(TelegramTopicRow).where(
                (TelegramTopicRow.chat_id == topic.chat_id)
                | (
                    (TelegramTopicRow.telegram_chat_id == topic.telegram_chat_id)
                    & (TelegramTopicRow.message_thread_id == topic.message_thread_id)
                )
            )
        )
        self.session.add(
            TelegramTopicRow(
                user_id=topic.user_id,
                telegram_chat_id=topic.telegram_chat_id,
                chat_id=topic.chat_id,
                message_thread_id=topic.message_thread_id,
                title=topic.title,
                icon_custom_emoji_id=topic.icon_custom_emoji_id,
            )
        )
        await self.session.flush()

    async def by_chat(self, chat_id: UUID) -> TelegramTopic | None:
        """The topic of an AI chat."""
        row = await self.session.scalar(
            select(TelegramTopicRow).where(TelegramTopicRow.chat_id == chat_id)
        )
        return _to_entity(row) if row else None

    async def by_thread(
        self, telegram_chat_id: int, message_thread_id: int
    ) -> TelegramTopic | None:
        """The link of a topic."""
        row = await self.session.scalar(
            select(TelegramTopicRow).where(
                TelegramTopicRow.telegram_chat_id == telegram_chat_id,
                TelegramTopicRow.message_thread_id == message_thread_id,
            )
        )
        return _to_entity(row) if row else None

    async def delete_by_chat(self, chat_id: UUID) -> None:
        """Forget the link of an AI chat."""
        await self.session.execute(
            delete(TelegramTopicRow).where(TelegramTopicRow.chat_id == chat_id)
        )
