"""Port: storage of notebook chat messages."""

from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.entities import NotebookMessage


class MessageRepository(Protocol):
    """Messages in `notebooks.messages` (one thread per notebook and user)."""

    async def add(self, message: NotebookMessage) -> None:
        """Insert a message."""
        ...

    async def get(self, message_id: UUID) -> NotebookMessage | None:
        """Return one message."""
        ...

    async def save(self, message: NotebookMessage) -> None:
        """Write feedback, `stopped`, content and token counts."""
        ...

    async def delete(self, message_id: UUID) -> None:
        """Delete one message."""
        ...

    async def last_seq(self, notebook_id: UUID, user_id: UUID) -> int:
        """Highest `seq` of the thread, 0 when empty."""
        ...

    async def list_tail(
        self, notebook_id: UUID, user_id: UUID, limit: int
    ) -> list[NotebookMessage]:
        """The last `limit` messages, ascending."""
        ...

    async def delete_all(self, notebook_id: UUID, user_id: UUID) -> int:
        """Delete the whole thread; return how many messages went."""
        ...

    async def delete_for_user(self, user_id: UUID) -> int:
        """Delete every thread of a user (in shared notebooks too); return the count."""
        ...
