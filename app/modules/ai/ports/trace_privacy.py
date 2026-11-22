"""The users' choice to keep their AI requests out of Langfuse as text."""

from typing import Protocol
from uuid import UUID


class TracingOptOut(Protocol):
    """Whether a user turned on `limit_ai_tracing` (read once per model call)."""

    async def limits_tracing(self, user_id: UUID) -> bool:
        """True when only the general chat text of this user may be traced."""
        ...
