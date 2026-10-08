"""Port: storage of chat messages."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.ai.domain.chat import ChatMessage


class MessageRepository(Protocol):
    """Messages of chats, ordered by `seq` (1, 2, 3, ... without gaps)."""

    async def add(self, message: ChatMessage) -> None:
        """Insert a message."""
        ...

    async def save(self, message: ChatMessage) -> None:
        """Write the message's tool calls and usage."""
        ...

    async def last_seq(self, chat_id: UUID) -> int:
        """Return the highest `seq` of the chat, 0 for an empty chat."""
        ...

    async def get_for_update(self, chat_id: UUID, seq: int) -> ChatMessage | None:
        """Return one message and lock its row until the transaction ends."""
        ...

    async def list_tail(self, chat_id: UUID, limit: int) -> list[ChatMessage]:
        """Return the last `limit` messages, oldest first."""
        ...

    async def list_range(
        self, chat_id: UUID, *, after_seq: int, up_to_seq: int | None
    ) -> list[ChatMessage]:
        """Return messages with after_seq < seq <= up_to_seq, oldest first."""
        ...

    async def chats_using_files(
        self, file_ids: Sequence[UUID]
    ) -> list[tuple[UUID, UUID, str]]:
        """Return (file_id, chat_id, title) of live chats whose messages use files."""
        ...
