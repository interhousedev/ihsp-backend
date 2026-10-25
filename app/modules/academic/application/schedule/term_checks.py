"""Checks shared by term creation and update."""

from uuid import UUID

from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain.schedule.errors import (
    TermDuplicateError,
    TermOverlapError,
)
from app.modules.academic.domain.schedule.term import Term, validate_term


async def check_term(
    uow: ScheduleUnitOfWork, term: Term, *, exclude_id: UUID | None
) -> None:
    """Validate the term's own rules, then overlap and unique year and half."""
    validate_term(term)
    clashes = await uow.terms.overlapping(
        term.starts_on, term.ends_on, exclude_id=exclude_id
    )
    if clashes:
        raise TermOverlapError(params={"term_ids": [str(c.id) for c in clashes]})
    if await uow.terms.year_half_taken(
        term.academic_year, term.half, exclude_id=exclude_id
    ):
        raise TermDuplicateError(
            params={"academic_year": term.academic_year, "half": term.half}
        )
