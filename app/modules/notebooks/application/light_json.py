"""One structured call of a light task, with budget accounting and retries."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Final
from uuid import UUID

from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.domain.tokens import estimate_cost
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiProviderError

PROVIDER_RETRIES: Final = 2  # after the first try
BACKOFF_SECONDS: Final = 2.0

Sleep = Callable[[float], Awaitable[None]]


class LightJson:
    """Source guides and notebook summaries: JSON from their own tasks' models.

    Provider errors are retried twice with a growing pause; every answer is counted
    in the student's weighted-token budget.
    """

    def __init__(
        self, *, llm: NotebookLlm, budget: NotebookBudget, sleep: Sleep = asyncio.sleep
    ) -> None:
        """Store the model, the budget and the sleep function (tests pass a fake)."""
        self.llm = llm
        self.budget = budget
        self.sleep = sleep

    async def call(
        self,
        owner_id: UUID,
        *,
        task: AiTask,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
        course: bool = False,
    ) -> dict[str, Any]:
        """Return the model's JSON document.

        `course=True` charges the owner's course pool (a course workspace).

        Raises:
            LimitReachedError: The student's budget does not cover the call.
            AiProviderError: The provider failed on every try.
            AiInvalidOutputError: The answer was not a JSON object.
        """
        max_tokens = self.llm.max_tokens(task, max_tokens)
        budget = self.budget.pool(course)
        await budget.require(
            owner_id, estimate_cost(len(system) + len(user), max_tokens)
        )
        attempt = 0
        while True:
            try:
                done = await self.llm.json(
                    task=task,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    schema_name=schema_name,
                    schema=schema,
                    max_tokens=max_tokens,
                )
            except AiProviderError:
                if attempt >= PROVIDER_RETRIES:
                    raise
                attempt += 1
                await self.sleep(BACKOFF_SECONDS * attempt)
            else:
                await budget.add(owner_id, done.usage.weighted)
                return done.data
