"""McpHistoryTools over the ai and notebooks modules."""

from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.interfaces.mcp.errors import McpNotFoundError
from app.modules.ai.domain.assistant import Assistant
from app.shared.actor import Actor
from app.shared.contracts.mcp_history import McpHistoryTools

if TYPE_CHECKING:
    from app.bootstrap.container import Container


class McpHistoryAdapter:
    """Owner-scoped history reads; a foreign id is not found."""

    def __init__(self, container: "Container") -> None:
        """Keep the container; modules are read lazily."""
        self.container = container

    async def list_chats(
        self, actor: Actor, *, cursor: str | None, limit: int
    ) -> dict[str, Any]:
        """The actor's student chats, newest first."""
        page = await self.container.ai.list_chats.execute(
            actor=actor, assistant=Assistant.STUDENT, cursor=cursor, limit=limit
        )
        return {
            "chats": [asdict(item) for item in page.items],
            "next_cursor": page.next_cursor,
        }

    async def get_chat(
        self, user_id: UUID, chat_id: UUID, *, after_seq: int, limit: int
    ) -> dict[str, Any]:
        """One page of a chat the user owns."""
        found = await self.container.ai.public.chat_history(
            user_id, chat_id, after_seq=after_seq, limit=limit
        )
        if found is None:
            raise McpNotFoundError()
        return found

    async def list_notebooks(
        self, actor: Actor, *, cursor: str | None, limit: int
    ) -> dict[str, Any]:
        """The actor's notebooks, pinned first then most recently opened."""
        page = await self.container.notebooks.list_notebooks.execute(
            actor, cursor=cursor, limit=limit
        )
        return {
            "notebooks": [
                {
                    "id": str(n.id),
                    "title": n.title,
                    "emoji": n.emoji,
                    "source_count": n.source_count,
                    "last_opened_at": n.last_opened_at,
                    "created_at": n.created_at,
                    "updated_at": n.updated_at,
                }
                for n in page.items
            ],
            "next_cursor": page.next_cursor,
        }

    async def get_notebook_chat(
        self, user_id: UUID, notebook_id: UUID, *, after_seq: int, limit: int
    ) -> dict[str, Any]:
        """One page of the thread of a notebook the user owns."""
        found = await self.container.notebooks.public.chat_page(
            user_id, notebook_id, after_seq=after_seq, limit=limit
        )
        if found is None:
            raise McpNotFoundError()
        return found

    async def get_notebook_notes(
        self, user_id: UUID, notebook_id: UUID, *, offset: int, limit: int
    ) -> dict[str, Any]:
        """One page of the notes of a notebook the user owns."""
        found = await self.container.notebooks.public.notes_page(
            user_id, notebook_id, offset=offset, limit=limit
        )
        if found is None:
            raise McpNotFoundError()
        return found


def build_history_tools(container: "Container") -> McpHistoryTools:
    """Build the backend of the history tools."""
    return McpHistoryAdapter(container)
