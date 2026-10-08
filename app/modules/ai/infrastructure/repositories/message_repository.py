"""SQL repository of chat messages."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.ai.domain.chat import ChatMessage, MessageContent, MessageRole
from app.modules.ai.domain.tool_call import ToolCall
from app.modules.ai.infrastructure.orm.chat import Chat as ChatRow
from app.modules.ai.infrastructure.orm.chat_message import ChatMessage as MessageRow

from sqlalchemy import ARRAY, Uuid, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: MessageRow) -> ChatMessage:
    return ChatMessage(
        id=row.id,
        chat_id=row.chat_id,
        seq=row.seq,
        role=MessageRole(row.role),
        content=MessageContent.model_validate(row.content),
        created_at=row.created_at,
        file_ids=list(row.file_ids or []),
        tool_calls=[ToolCall.model_validate(c) for c in row.tool_calls or []],
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
    )


def _calls_json(message: ChatMessage) -> list[dict[str, object]] | None:
    if not message.tool_calls:
        return None
    return [call.model_dump(mode="json") for call in message.tool_calls]


class SqlMessageRepository:
    """Messages in `ai.chat_messages`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, message: ChatMessage) -> None:
        """Insert a message."""
        self.session.add(
            MessageRow(
                id=message.id,
                chat_id=message.chat_id,
                seq=message.seq,
                role=message.role.value,
                content=message.content.model_dump(mode="json"),
                file_ids=message.file_ids,
                tool_calls=_calls_json(message),
                tokens_in=message.tokens_in,
                tokens_out=message.tokens_out,
                created_at=message.created_at,
            )
        )
        await self.session.flush()

    async def save(self, message: ChatMessage) -> None:
        """Write the message's tool calls and usage."""
        row = await self.session.get(MessageRow, message.id)
        if row is None:
            return
        row.tool_calls = _calls_json(message)
        row.tokens_in = message.tokens_in
        row.tokens_out = message.tokens_out
        await self.session.flush()

    async def last_seq(self, chat_id: UUID) -> int:
        """Return the highest `seq` of the chat, 0 for an empty chat."""
        stmt = select(func.coalesce(func.max(MessageRow.seq), 0)).where(
            MessageRow.chat_id == chat_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_for_update(self, chat_id: UUID, seq: int) -> ChatMessage | None:
        """Return one message and lock its row until the transaction ends."""
        stmt = (
            select(MessageRow)
            .where(MessageRow.chat_id == chat_id, MessageRow.seq == seq)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def list_tail(self, chat_id: UUID, limit: int) -> list[ChatMessage]:
        """Return the last `limit` messages, oldest first."""
        stmt = (
            select(MessageRow)
            .where(MessageRow.chat_id == chat_id)
            .order_by(MessageRow.seq.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(r) for r in reversed(rows)]

    async def list_range(
        self, chat_id: UUID, *, after_seq: int, up_to_seq: int | None
    ) -> list[ChatMessage]:
        """Return messages with after_seq < seq <= up_to_seq, oldest first."""
        stmt = select(MessageRow).where(
            MessageRow.chat_id == chat_id, MessageRow.seq > after_seq
        )
        if up_to_seq is not None:
            stmt = stmt.where(MessageRow.seq <= up_to_seq)
        stmt = stmt.order_by(MessageRow.seq).execution_options(populate_existing=True)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(r) for r in rows]

    async def chats_using_files(
        self, file_ids: Sequence[UUID]
    ) -> list[tuple[UUID, UUID, str]]:
        """Return (file_id, chat_id, title) of live chats whose messages use files."""
        if not file_ids:
            return []
        wanted = set(file_ids)
        stmt = (
            select(MessageRow.chat_id, MessageRow.file_ids, ChatRow.title)
            .join(ChatRow, ChatRow.id == MessageRow.chat_id)
            .where(
                MessageRow.file_ids.op("&&", is_comparison=True)(
                    literal(list(wanted), ARRAY(Uuid))
                ),
                ChatRow.deleted_at.is_(None),
            )
        )
        found: dict[tuple[UUID, UUID], str] = {}
        for chat_id, message_files, title in (await self.session.execute(stmt)).all():
            for file_id in wanted.intersection(message_files or []):
                found[(file_id, chat_id)] = title
        return [
            (file_id, chat_id, title) for (file_id, chat_id), title in found.items()
        ]
