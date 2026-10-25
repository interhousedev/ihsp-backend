"""Port: storage of chats."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat


class ChatRepository(Protocol):
    """Chats of the assistants."""

    async def add(self, chat: Chat) -> None:
        """Insert a new chat."""
        ...

    async def get(self, chat_id: UUID) -> Chat | None:
        """Return the chat, deleted or not."""
        ...

    async def get_for_update(self, chat_id: UUID) -> Chat | None:
        """Return the chat and lock its row until the transaction ends."""
        ...

    async def save(self, chat: Chat) -> None:
        """Write the chat's fields."""
        ...

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
        """Return the owner's live chats, newest first, after the cursor.

        `title_contains` keeps the chats whose title has this text (any case,
        wildcards are literal characters); `course_id` keeps the author chats of
        that course (``scope.course_id``).
        """
        ...

    async def with_pending(self, owner_id: UUID) -> list[Chat]:
        """Return the owner's live chats that have approvals waiting."""
        ...

    async def purge_admin_chats(self, last_message_before: datetime) -> int:
        """Hard-delete old Administration chats with their messages; return count."""
        ...
