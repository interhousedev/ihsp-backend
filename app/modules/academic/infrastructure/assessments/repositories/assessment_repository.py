"""SQL repository of assessments."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.assessments.ports.repositories import (
    AssessmentQuery,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.assessments.records import Assessment, NewAssessment
from app.modules.academic.infrastructure.marks.sql_helpers import overlaps
from app.modules.academic.infrastructure.orm.assessment import Assessment as Row
from app.shared.ids import new_id

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


def to_entity(row: Row) -> Assessment:
    """Map a row to the domain record."""
    return Assessment(
        id=row.id,
        subject_id=row.subject_id,
        audience=tuple(row.audience),
        kind=row.kind,  # type: ignore[arg-type]  # CHECK-constrained text
        title=row.title,
        date=row.date,
        lesson_id=row.lesson_id,
        starts_at=row.starts_at,
        room=row.room,
        status=row.status,  # type: ignore[arg-type]
        source=row.source,  # type: ignore[arg-type]
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        control=row.control,  # type: ignore[arg-type]
    )


class SqlAssessmentRepository:
    """Implements AssessmentRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def add(self, new: NewAssessment) -> Assessment:
        """Insert a control and return it with its stored timestamps."""
        row = Row(
            id=new_id(),
            subject_id=new.subject_id,
            audience=list(new.audience),
            kind=new.kind,
            title=new.title,
            date=new.date,
            lesson_id=new.lesson_id,
            starts_at=new.starts_at,
            room=new.room,
            status=new.status,
            source=new.source,
            note=new.note,
            created_by=new.created_by,
            control=new.control,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return to_entity(row)

    async def get(self, assessment_id: UUID) -> Assessment | None:
        """Return a control by id, whatever its status."""
        row = await self.session.get(Row, assessment_id)
        return None if row is None else to_entity(row)

    async def save(self, assessment: Assessment) -> Assessment:
        """Write the editable fields of a control and return it."""
        row = await self.session.get(Row, assessment.id)
        if row is None:
            raise LookupError(f"assessment {assessment.id} is not stored")
        row.subject_id = assessment.subject_id
        row.audience = list(assessment.audience)
        row.kind = assessment.kind
        row.title = assessment.title
        row.date = assessment.date
        row.lesson_id = assessment.lesson_id
        row.starts_at = assessment.starts_at
        row.room = assessment.room
        row.status = assessment.status
        row.note = assessment.note
        row.control = assessment.control
        await self.session.flush()
        await self.session.refresh(row)
        return to_entity(row)

    async def find(self, query: AssessmentQuery) -> list[Assessment]:
        """Return controls matching the query, oldest first."""
        conditions: list[Any] = [Row.status.in_(list(query.statuses))]
        if query.since is not None:
            conditions.append(Row.date >= query.since)
        if query.until is not None:
            conditions.append(Row.date <= query.until)
        if query.subject_id is not None:
            conditions.append(Row.subject_id == query.subject_id)
        if query.group_id is not None:
            conditions.append(
                overlaps(Row.audience, audience_keys.student_keys(query.group_id, None))
            )
        if query.audience is not None:
            conditions.append(overlaps(Row.audience, query.audience))
        if query.kind is not None:
            conditions.append(Row.kind == query.kind)
        if query.source is not None:
            conditions.append(Row.source == query.source)
        stmt = (
            sa.select(Row)
            .where(*conditions)
            .order_by(Row.date, Row.starts_at.asc().nulls_last(), Row.id)
            .limit(query.limit)
        )
        return [to_entity(row) for row in await self.session.scalars(stmt)]
