"""Use case: the remaining AI budget (AI-8)."""

from app.modules.ai.application.assistant_profile import require_assistant_role
from app.modules.ai.application.budget import BudgetService, UsageInfo
from app.modules.ai.domain.assistant import Assistant, default_assistant
from app.shared.actor import Actor


class GetUsage:
    """Returns session and day usage for one assistant."""

    def __init__(self, *, budget: BudgetService) -> None:
        """Store the budget service."""
        self.budget = budget

    async def execute(self, *, actor: Actor, assistant: Assistant | None) -> UsageInfo:
        """Return the usage; the assistant defaults to the one the roles allow."""
        chosen = assistant or default_assistant(actor)
        require_assistant_role(actor, chosen)
        return await self.budget.usage(actor.user_id, chosen)
