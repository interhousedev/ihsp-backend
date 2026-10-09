"""SQL repository of chats."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat, ChatTier
from app.modules.ai.domain.chat_scope import ChatScope
from app.modules.ai.infrastructure.orm.chat import Chat as ChatRow

from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: ChatRow) -> Chat:
    return Chat(
        id=row.id,
        owner_id=row.owner_id,
        assistant=Assistant(row.assistant),
        title=row.title,
        model=row.model,
        last_message_at=row.last_message_at,
        pending_approvals=int(row.pending_approvals or 0),
        deleted_at=row.deleted_at,
        tier=ChatTier(row.tier),
        scope=ChatScope.model_validate(row.scope) if row.scope else None,
    )


def _apply(row: ChatRow, chat: Chat) -> None:
    row.owner_id = chat.owner_id
    row.assistant = chat.assistant.value
    row.title = chat.title
    row.model = chat.model
    row.last_message_at = chat.last_message_at
    row.pending_approvals = chat.pending_approvals
    row.deleted_at = chat.deleted_at
    row.tier = chat.tier.value
    row.scope = chat.scope.model_dump(mode="json") if chat.scope else None


def _like_pattern(query: str) -> str:
    """Return a LIKE pattern that matches the text anywhere; wildcards are literal."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SqlChatRepository:
    """Chats in `ai.chats`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, chat: Chat) -> None:
        """Insert a new chat."""
        row = ChatRow(id=chat.id)
        _apply(row, chat)
        self.session.add(row)
        await self.session.flush()

    async def _row(self, chat_id: UUID, *, lock: bool) -> ChatRow | None:
        stmt = select(ChatRow).where(ChatRow.id == chat_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get(self, chat_id: UUID) -> Chat | None:
        """Return the chat, deleted or not."""
        row = await self._row(chat_id, lock=False)
        return _to_entity(row) if row else None

    async def get_for_update(self, chat_id: UUID) -> Chat | None:
        """Return the chat and lock its row until the transaction ends."""
        row = await self._row(chat_id, lock=True)
        return _to_entity(row) if row else None

    async def save(self, chat: Chat) -> None:
        """Write the chat's fields."""
        row = await self._row(chat.id, lock=False)
        if row is None:
            return
        _apply(row, chat)
        await self.session.flush()

    async def list_for_owner(
        self,
        owner_id: UUID,
        assistant: Assistant,
        *,
        before: tuple[datetime, UUID] | None,
        limit: int,
        title_contains: str | None = None,
        course_id: UUID | None = None,
    ) -> list[Chat]:
        """Return the owner's live chats, newest first, after the cursor."""
        stmt = select(ChatRow).where(
            ChatRow.owner_id == owner_id,
            ChatRow.assistant == assistant.value,
            ChatRow.deleted_at.is_(None),
        )
        if course_id is not None:
            stmt = stmt.where(ChatRow.scope["course_id"].astext == str(course_id))
        if title_contains:
            stmt = stmt.where(
                ChatRow.title.ilike(_like_pattern(title_contains), escape="\\")
            )
        if before is not None:
            stmt = stmt.where(
                tuple_(ChatRow.last_message_at, ChatRow.id) < (before[0], before[1])
            )
        stmt = stmt.order_by(ChatRow.last_message_at.desc(), ChatRow.id.desc())
        rows = (await self.session.execute(stmt.limit(limit))).scalars().all()
        return [_to_entity(r) for r in rows]

    async def with_pending(self, owner_id: UUID) -> list[Chat]:
        """Return the owner's live chats that have approvals waiting."""
        stmt = select(ChatRow).where(
            ChatRow.owner_id == owner_id,
            ChatRow.deleted_at.is_(None),
            ChatRow.pending_approvals > 0,
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(r) for r in rows]

    async def purge_admin_chats(self, last_message_before: datetime) -> int:
        """Hard-delete old Administration chats (messages cascade)."""
        stmt = (
            delete(ChatRow)
            .where(
                ChatRow.assistant == Assistant.ADMIN.value,
                ChatRow.last_message_at < last_message_before,
            )
            .returning(ChatRow.id)
        )
        deleted: Any = (await self.session.execute(stmt)).all()
        return len(deleted)
