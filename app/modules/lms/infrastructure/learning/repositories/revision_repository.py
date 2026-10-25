"""SQLAlchemy repository of step revisions (read only)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.lms.domain.learning.entities import RevisionData
from app.modules.lms.domain.step_content import StepContent
from app.modules.lms.infrastructure.orm.step_revision import StepRevision

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlRevisionRepository:
    """Revisions of the lms schema; their content is immutable."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def get(self, revision_id: UUID) -> RevisionData | None:
        """Return a revision with its parsed content."""
        row = await self.session.get(StepRevision, revision_id)
        return None if row is None else _to_entity(row)

    async def get_many(self, revision_ids: Sequence[UUID]) -> dict[UUID, RevisionData]:
        """Return the revisions that exist, by id, in one query."""
        if not revision_ids:
            return {}
        rows = await self.session.scalars(
            select(StepRevision).where(StepRevision.id.in_(revision_ids))
        )
        return {row.id: _to_entity(row) for row in rows}


def _to_entity(row: StepRevision) -> RevisionData:
    """Map the ORM row to the entity, parsing its content."""
    return RevisionData(
        id=row.id,
        step_id=row.step_id,
        kind=row.kind,
        content=StepContent.model_validate(row.content),
    )
