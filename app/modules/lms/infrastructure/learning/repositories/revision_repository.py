"""SQLAlchemy repository of step revisions (read only)."""

from uuid import UUID

from app.modules.lms.domain.learning.entities import RevisionData
from app.modules.lms.domain.step_content import StepContent
from app.modules.lms.infrastructure.orm.step_revision import StepRevision

from sqlalchemy.ext.asyncio import AsyncSession


class SqlRevisionRepository:
    """Revisions of the lms schema; their content is immutable."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def get(self, revision_id: UUID) -> RevisionData | None:
        """Return a revision with its parsed content."""
        row = await self.session.get(StepRevision, revision_id)
        if row is None:
            return None
        return RevisionData(
            id=row.id,
            step_id=row.step_id,
            kind=row.kind,
            content=StepContent.model_validate(row.content),
        )
