"""SQLAlchemy repository of steps (identity only)."""

from uuid import UUID

from app.modules.lms.domain.learning.entities import LearningStep
from app.modules.lms.infrastructure.orm.course_step import CourseStep

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlStepRepository:
    """Steps of the lms schema; learners never read the draft."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def get(self, step_id: UUID) -> LearningStep | None:
        """Return a step by id."""
        row = await self.session.execute(
            select(CourseStep.id, CourseStep.course_id).where(CourseStep.id == step_id)
        )
        found = row.first()
        return (
            None
            if found is None
            else LearningStep(id=found.id, course_id=found.course_id)
        )
