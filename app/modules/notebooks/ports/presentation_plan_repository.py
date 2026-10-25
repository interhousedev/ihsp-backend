"""Port: presentation plans (PLAN)."""

from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.presentation_plan import PresentationPlan


class PresentationPlanRepository(Protocol):
    """Slide outlines of notebooks."""

    async def add(self, plan: PresentationPlan) -> None:
        """Insert a new plan."""
        ...

    async def get(self, plan_id: UUID) -> PresentationPlan | None:
        """The plan with this id, if any."""
        ...

    async def get_for_update(self, plan_id: UUID) -> PresentationPlan | None:
        """The plan with this id, locked for the transaction."""
        ...

    async def save(self, plan: PresentationPlan) -> None:
        """Store the changed fields of a plan."""
        ...
