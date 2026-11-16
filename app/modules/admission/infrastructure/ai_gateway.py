"""Adapter: the admission AI port over the notebook LLM client."""

from typing import Any

from app.modules.notebooks.application.llm import NotebookLlm
from app.shared.ai_tasks import AiTask


class GatewayStructuredAi:
    """Calls `NotebookLlm.json` with one user message."""

    def __init__(self, llm: NotebookLlm) -> None:
        """Keep the client."""
        self._llm = llm

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
        done = await self._llm.json(
            task=task,
            system=system,
            messages=[{"role": "user", "content": user}],
            schema_name=schema_name,
            schema=schema,
            max_tokens=max_tokens,
        )
        return done.data, done.model
