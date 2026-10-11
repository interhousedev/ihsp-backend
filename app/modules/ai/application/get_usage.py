"""Use case: the remaining AI budget (AI-8)."""

from uuid import UUID

from app.modules.ai.application.budget import BudgetService, UsageInfo
from app.modules.ai.application.owned_chat import ChatGuard
from app.modules.ai.domain.assistant import Assistant, default_assistant
from app.shared.actor import Actor


class GetUsage:
    """Returns session and day usage for one assistant."""

    def __init__(self, *, budget: BudgetService, guard: ChatGuard) -> None:
        """Store the budget service and the access checks."""
        self.budget = budget
        self.guard = guard

    async def execute(
        self,
        *,
        actor: Actor,
        assistant: Assistant | None,
        course_id: UUID | None = None,
    ) -> UsageInfo:
        """Return the usage; the assistant defaults to the one the roles allow.

        The course author assistant's pool is the course staff pool; asking for it
        needs `course_id` with the ``edit`` permission.
        """
        chosen = assistant or default_assistant(actor)
        await self.guard.assistant(actor, chosen, course_id)
        return await self.budget.usage_for(actor, chosen)
