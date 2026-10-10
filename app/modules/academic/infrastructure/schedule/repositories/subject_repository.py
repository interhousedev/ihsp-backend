"""SQL repository of subjects."""

from collections.abc import Collection
from uuid import UUID

from app.modules.academic.domain.schedule.subject import Subject
from app.modules.academic.infrastructure.orm import Subject as SubjectRow
from app.modules.academic.infrastructure.schedule.like import ESCAPE, like_pattern
from app.modules.academic.infrastructure.schedule.mappers import (
    subject_apply,
    subject_new_row,
    subject_to_entity,
)

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlSubjectRepository:
    """Subjects in the academic schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def get(self, subject_id: UUID) -> Subject | None:
        """Return the subject or None."""
        row = await self.session.get(SubjectRow, subject_id)
        return subject_to_entity(row) if row else None

    async def get_many(self, subject_ids: Collection[UUID]) -> dict[UUID, Subject]:
        """Return the subjects that exist, by id."""
        if not subject_ids:
            return {}
        rows = await self.session.scalars(
            select(SubjectRow).where(SubjectRow.id.in_(list(subject_ids)))
        )
        return {row.id: subject_to_entity(row) for row in rows}

    async def get_by_emis_id(self, emis_subject_id: int) -> Subject | None:
        """Return the subject linked to an EMIS subject."""
        stmt = select(SubjectRow).where(SubjectRow.emis_subject_id == emis_subject_id)
        row = (await self.session.scalars(stmt.limit(1))).first()
        return subject_to_entity(row) if row else None

    async def get_by_emis_ids(
        self, emis_subject_ids: Collection[int]
    ) -> dict[int, Subject]:
        """Return the subjects linked to EMIS subjects, by EMIS id."""
        if not emis_subject_ids:
            return {}
        rows = await self.session.scalars(
            select(SubjectRow).where(
                SubjectRow.emis_subject_id.in_(list(emis_subject_ids))
            )
        )
        return {
            row.emis_subject_id: subject_to_entity(row)
            for row in rows
            if row.emis_subject_id is not None
        }

    async def add(self, subject: Subject) -> None:
        """Insert a subject."""
        self.session.add(subject_new_row(subject))
        await self.session.flush()

    async def save(self, subject: Subject) -> None:
        """Write the changes of a subject."""
        row = await self.session.get(SubjectRow, subject.id)
        if row is None:
            return
        subject_apply(row, subject)
        await self.session.flush()

    async def search(self, query: str | None) -> list[Subject]:
        """Return subjects whose names contain the query, ordered by name."""
        label = func.coalesce(
            func.nullif(SubjectRow.name["ru"].astext, ""),
            func.nullif(SubjectRow.name["uz"].astext, ""),
            SubjectRow.name["en"].astext,
        )
        stmt = select(SubjectRow).order_by(label, SubjectRow.id)
        if query:
            pattern = like_pattern(query)
            stmt = stmt.where(
                or_(
                    SubjectRow.name["uz"].astext.ilike(pattern, escape=ESCAPE),
                    SubjectRow.name["ru"].astext.ilike(pattern, escape=ESCAPE),
                    SubjectRow.name["en"].astext.ilike(pattern, escape=ESCAPE),
                    SubjectRow.short_name.ilike(pattern, escape=ESCAPE),
                )
            )
        return [subject_to_entity(row) for row in await self.session.scalars(stmt)]
