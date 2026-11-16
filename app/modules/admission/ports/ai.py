"""Port: structured JSON answers of an admission AI task."""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

from app.shared.ai_tasks import AiTask


class StructuredAi(Protocol):
    """One strict-schema model call; student text never leaves `messages`."""

    async def json(
        self,
        *,
        task: AiTask,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
    ) -> tuple[dict[str, Any], str]:
        """Return the parsed document and the model name."""
        ...


class PromptSource(Protocol):
    """The system prompt of a task: the active version, else the built-in text."""

    async def text(self, task: AiTask, name: str, locale: str) -> str:
        """Return the raw (unfilled) prompt `name` of `task` for the locale."""
        ...


# The soft limit in force for a user right now (None: unlimited, as for staff).
QuotaOf = Callable[[UUID], Awaitable[int | None]]
