"""Port: stored goal-plan milestones."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.goal_plan import GoalMilestone


class GoalRepository(Protocol):
    """A student's milestones."""

    async def list_for(self, student_id: UUID) -> list[GoalMilestone]:
        """Return the milestones in display order."""
        ...

    async def get(self, milestone_id: UUID) -> GoalMilestone | None:
        """Return one milestone."""
        ...

    async def add(self, milestone: GoalMilestone) -> GoalMilestone:
        """Insert a milestone."""
        ...

    async def update(self, milestone: GoalMilestone) -> GoalMilestone:
        """Store it (compare-and-set on `lock_version`)."""
        ...

    async def delete(self, milestone_id: UUID) -> None:
        """Delete a milestone."""
        ...
