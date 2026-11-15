"""What the history MCP tools need (implemented in bootstrap/adapters/mcp_history.py).

The caller's own AI chats and notebooks, listed and read page by page. Someone else's
or a missing id raises a NotFoundError, the same for both.
"""

from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor


class McpHistoryTools(Protocol):
    """The history tools of the Students server."""

    async def list_chats(
        self, actor: Actor, *, cursor: str | None, limit: int
    ) -> dict[str, Any]:
        """`{"chats": [...], "next_cursor"}`, newest first."""
        ...

    async def get_chat(
        self, user_id: UUID, chat_id: UUID, *, after_seq: int, limit: int
    ) -> dict[str, Any]:
        """One page of the owner's chat messages, oldest first."""
        ...

    async def list_notebooks(
        self, actor: Actor, *, cursor: str | None, limit: int
    ) -> dict[str, Any]:
        """`{"notebooks": [...], "next_cursor"}`, pinned then recently opened."""
        ...

    async def get_notebook_chat(
        self, user_id: UUID, notebook_id: UUID, *, after_seq: int, limit: int
    ) -> dict[str, Any]:
        """One page of the owner's chat thread in a notebook."""
        ...

    async def get_notebook_notes(
        self, user_id: UUID, notebook_id: UUID, *, offset: int, limit: int
    ) -> dict[str, Any]:
        """One page of the notes of the owner's notebook."""
        ...
