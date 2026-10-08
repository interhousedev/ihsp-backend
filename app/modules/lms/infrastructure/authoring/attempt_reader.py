"""SQLAlchemy read-only access to test attempts."""

from typing import Any
from uuid import UUID

from app.modules.lms.infrastructure.orm import CourseStep as StepRow
from app.modules.lms.infrastructure.orm import TestAttempt as AttemptRow

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAttemptReader:
    """Reads `lms.test_attempts` for the MCP review tools."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the reader to the unit of work's session."""
        self.session = session

    async def recent_for_course(
        self, course_id: UUID, limit: int
    ) -> list[dict[str, Any]]:
        """Return the most recent attempts of a course as JSON-compatible dicts."""
        statement = (
            select(AttemptRow)
            .join(StepRow, StepRow.id == AttemptRow.step_id)
            .where(StepRow.course_id == course_id)
            .order_by(AttemptRow.started_at.desc(), AttemptRow.id.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return [_to_dict(r) for r in (await self.session.scalars(statement))]


def _to_dict(row: AttemptRow) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "step_id": str(row.step_id),
        "revision_id": str(row.revision_id),
        "block_id": row.block_id,
        "attempt_no": row.attempt_no,
        "is_preview": row.is_preview,
        "started_at": row.started_at.isoformat(),
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "score": None if row.score is None else float(row.score),
        "max_score": float(row.max_score),
        "passed": row.passed,
        "override_score": (
            None if row.override_score is None else float(row.override_score)
        ),
    }
