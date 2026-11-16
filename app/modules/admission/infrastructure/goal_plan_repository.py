"""SQL repository of goal-plan milestones."""

from typing import cast
from uuid import UUID

from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.goal_plan import (
    GoalMilestone,
    GoalSource,
    GoalStatus,
)
from app.modules.admission.infrastructure.orm.profile import GoalMilestoneRow
from app.shared.ids import new_id

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


def _milestone(row: GoalMilestoneRow) -> GoalMilestone:
    return GoalMilestone(
        id=row.id,
        student_id=row.student_id,
        title=row.title,
        item_id=row.item_id,
        due_month=row.due_month,
        target_value=row.target_value,
        status=cast(GoalStatus, row.status),
        done_at=row.done_at,
        source=cast(GoalSource, row.source),
        sort_order=row.sort_order,
        lock_version=row.lock_version,
    )


class SqlGoalRepository:
    """Milestones on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def list_for(self, student_id: UUID) -> list[GoalMilestone]:
        """Return the milestones by sort order, then month."""
        rows = await self._s.scalars(
            select(GoalMilestoneRow)
            .where(GoalMilestoneRow.student_id == student_id)
            .order_by(
                GoalMilestoneRow.sort_order,
                GoalMilestoneRow.due_month.asc().nulls_last(),
                GoalMilestoneRow.id,
            )
        )
        return [_milestone(r) for r in rows]

    async def get(self, milestone_id: UUID) -> GoalMilestone | None:
        """Return one milestone."""
        row = await self._s.get(GoalMilestoneRow, milestone_id)
        return _milestone(row) if row else None

    async def add(self, milestone: GoalMilestone) -> GoalMilestone:
        """Insert a milestone."""
        row = GoalMilestoneRow(
            id=milestone.id or new_id(),
            student_id=milestone.student_id,
            item_id=milestone.item_id,
            title=milestone.title,
            due_month=milestone.due_month,
            target_value=milestone.target_value,
            status=milestone.status,
            done_at=milestone.done_at,
            source=milestone.source,
            sort_order=milestone.sort_order,
            lock_version=0,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _milestone(row)

    async def update(self, milestone: GoalMilestone) -> GoalMilestone:
        """Store the fields and bump the lock version (compare-and-set)."""
        row = await self._s.get(GoalMilestoneRow, milestone.id)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != milestone.lock_version:
            raise AdmissionConflictError()
        row.item_id = milestone.item_id
        row.title = milestone.title
        row.due_month = milestone.due_month
        row.target_value = milestone.target_value
        row.status = milestone.status
        row.done_at = milestone.done_at
        row.sort_order = milestone.sort_order
        row.lock_version = milestone.lock_version + 1
        await self._s.flush()
        await self._s.refresh(row)
        return _milestone(row)

    async def delete(self, milestone_id: UUID) -> None:
        """Delete the milestone."""
        await self._s.execute(
            delete(GoalMilestoneRow).where(GoalMilestoneRow.id == milestone_id)
        )
