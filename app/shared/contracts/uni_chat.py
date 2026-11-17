"""The admission university chat as the AI module sees it.

A student's chat about one target university is an ordinary student chat of the
AI module; admission links it to the university. The AI module asks this source
for the university brief (a system prompt block) and for the research tool.
"""

from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor


class UniChatSource(Protocol):
    """The university context of a chat (None when the chat is not a uni chat)."""

    async def brief(self, chat_id: UUID, owner_id: UUID) -> str | None:
        """The catalog materials and the student's application, or None."""
        ...

    async def research(
        self, actor: Actor, chat_id: UUID, query: str, locale: str
    ) -> dict[str, Any] | None:
        """Web pages about the chat's university for a query, or None."""
        ...

    async def is_uni_chat(self, chat_id: UUID, owner_id: UUID) -> bool:
        """Whether the chat is the owner's university chat (offers the tool)."""
        ...
