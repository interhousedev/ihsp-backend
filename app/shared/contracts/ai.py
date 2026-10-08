"""AI contracts (provider: ai module; LlmGateway: OpenRouter adapter)."""

from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor


class AiQueries(Protocol):
    """Read access to AI chats for other modules."""

    async def pending_approvals(self, user_id: UUID) -> int:
        """Return how many tool calls wait for the user's approval."""
        ...

    async def chat_for_share(
        self, chat_id: UUID, until_seq: int | None
    ) -> dict[str, Any] | None:
        """Return {"title", "owner_id", "messages": [...]} for a shared chat.

        Each message has role, text and tool_notes (list of str).
        """
        ...

    async def chat_owner(self, chat_id: UUID) -> UUID | None:
        """Return the chat owner's id."""
        ...


class LlmGateway(Protocol):
    """Language model access (OpenRouter in production, a fake in tests)."""

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Return {"text", "tool_calls": [{"id","name","arguments"}], "usage"}.

        usage is {"input": int, "output": int, "cached": int}.
        """
        ...


class AdminToolBackend(Protocol):
    """Admin assistant tools (provider: I1 adapter over identity/academic/admin)."""

    async def call(
        self, tool: str, arguments: dict[str, Any], actor: Actor
    ) -> dict[str, Any]:
        """Run an admin tool as the actor."""
        ...
