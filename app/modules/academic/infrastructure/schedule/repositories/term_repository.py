"""SQL repository of terms."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain.schedule.errors import (
    TermDuplicateError,
    TermOverlapError,
)
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.infrastructure.orm import Term as TermRow
from app.modules.academic.infrastructure.schedule.mappers import (
    term_apply,
    term_new_row,
    term_to_entity,
)

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _term_integrity_error(error: IntegrityError) -> Exception:
    text = str(error.orig)
    if "uq_terms_academic_year_half" in text:
        return TermDuplicateError()
    return TermOverlapError()


class SqlTermRepository:
    """Terms in the academic schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def get(self, term_id: UUID) -> Term | None:
        """Return the term or None."""
        row = await self.session.get(TermRow, term_id)
        return term_to_entity(row) if row else None

    async def list_all(self) -> list[Term]:
        """Return all terms ordered by start date."""
        rows = await self.session.scalars(select(TermRow).order_by(TermRow.starts_on))
        return [term_to_entity(row) for row in rows]

    async def add(self, term: Term) -> None:
        """Insert a term."""
        self.session.add(term_new_row(term))
        await self._flush()

    async def save(self, term: Term) -> None:
        """Write the changes of a term."""
        row = await self.session.get(TermRow, term.id)
        if row is None:
            return
        term_apply(row, term)
        await self._flush()

    async def _flush(self) -> None:
        try:
            await self.session.flush()
        except IntegrityError as error:
            raise _term_integrity_error(error) from error

    async def overlapping(
        self, starts_on: dt.date, ends_on: dt.date, *, exclude_id: UUID | None
    ) -> list[Term]:
        """Return terms whose dates intersect the range."""
        stmt = select(TermRow).where(
            TermRow.starts_on <= ends_on, TermRow.ends_on >= starts_on
        )
        if exclude_id is not None:
            stmt = stmt.where(TermRow.id != exclude_id)
        rows = await self.session.scalars(stmt.order_by(TermRow.starts_on))
        return [term_to_entity(row) for row in rows]

    async def year_half_taken(
        self, academic_year: str, half: int, *, exclude_id: UUID | None
    ) -> bool:
        """Return True if another term has this academic year and half."""
        stmt = select(TermRow.id).where(
            TermRow.academic_year == academic_year, TermRow.half == half
        )
        if exclude_id is not None:
            stmt = stmt.where(TermRow.id != exclude_id)
        return (await self.session.scalars(stmt.limit(1))).first() is not None

    async def containing(self, day: dt.date) -> Term | None:
        """Return the term whose dates contain the day."""
        stmt = select(TermRow).where(TermRow.starts_on <= day, TermRow.ends_on >= day)
        row = (await self.session.scalars(stmt.limit(1))).first()
        return term_to_entity(row) if row else None
