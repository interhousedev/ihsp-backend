"""SQL repository of notebook chat messages."""

from typing import Any, cast
from uuid import UUID

from app.modules.notebooks.domain.entities import MessageContent, NotebookMessage
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.infrastructure.orm.message import Message as MessageRow

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: MessageRow) -> NotebookMessage:
    return NotebookMessage(
        id=row.id,
        notebook_id=row.notebook_id,
        user_id=row.user_id,
        seq=int(row.seq),
        role=MessageRole(row.role),
        content=MessageContent.model_validate(row.content),
        created_at=row.created_at,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        tokens_cached=row.tokens_cached,
        weighted=row.weighted,
        model=row.model,
        feedback=row.feedback,
        stopped=row.stopped,
    )


def _apply(row: MessageRow, message: NotebookMessage) -> None:
    row.notebook_id = message.notebook_id
    row.user_id = message.user_id
    row.seq = message.seq
    row.role = message.role.value
    row.content = message.content.model_dump(mode="json")
    row.tokens_in = message.tokens_in
    row.tokens_out = message.tokens_out
    row.tokens_cached = message.tokens_cached
    row.weighted = message.weighted
    row.model = message.model
    row.feedback = message.feedback
    row.stopped = message.stopped


class SqlMessageRepository:
    """Messages in `notebooks.messages` (one thread per notebook and user)."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, message: NotebookMessage) -> None:
        """Insert a message."""
        row = MessageRow(id=message.id)
        _apply(row, message)
        row.created_at = message.created_at
        row.updated_at = message.created_at
        self.session.add(row)
        await self.session.flush()

    async def get(self, message_id: UUID) -> NotebookMessage | None:
        """Return one message."""
        stmt = (
            select(MessageRow)
            .where(MessageRow.id == message_id)
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def save(self, message: NotebookMessage) -> None:
        """Write feedback, `stopped`, content, model and token counts."""
        stmt = select(MessageRow).where(MessageRow.id == message.id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return
        _apply(row, message)
        await self.session.flush()

    async def delete(self, message_id: UUID) -> None:
        """Delete one message."""
        await self.session.execute(
            delete(MessageRow).where(MessageRow.id == message_id),
            execution_options={"synchronize_session": False},
        )

    async def last_seq(self, notebook_id: UUID, user_id: UUID) -> int:
        """Highest `seq` of the thread, 0 when empty."""
        stmt = select(func.coalesce(func.max(MessageRow.seq), 0)).where(
            MessageRow.notebook_id == notebook_id, MessageRow.user_id == user_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_tail(
        self, notebook_id: UUID, user_id: UUID, limit: int
    ) -> list[NotebookMessage]:
        """The last `limit` messages, ascending."""
        stmt = (
            select(MessageRow)
            .where(MessageRow.notebook_id == notebook_id, MessageRow.user_id == user_id)
            .order_by(MessageRow.seq.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in reversed(rows)]

    async def delete_all(self, notebook_id: UUID, user_id: UUID) -> int:
        """Delete the whole thread; return how many messages went."""
        result = await self.session.execute(
            delete(MessageRow).where(
                MessageRow.notebook_id == notebook_id, MessageRow.user_id == user_id
            ),
            execution_options={"synchronize_session": False},
        )
        return int(cast("CursorResult[Any]", result).rowcount)

    async def delete_for_user(self, user_id: UUID) -> int:
        """Delete every thread of a user (in shared notebooks too); return the count."""
        result = await self.session.execute(
            delete(MessageRow).where(MessageRow.user_id == user_id),
            execution_options={"synchronize_session": False},
        )
        return int(cast("CursorResult[Any]", result).rowcount)
