"""Mapping terms to read models."""

import datetime as dt
from collections.abc import Sequence

from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.domain.schedule.term import Term, pick_current_term


def term_data(term: Term, *, is_current: bool) -> TermData:
    """Return the term with the is_current flag."""
    return TermData(
        id=term.id,
        academic_year=term.academic_year,
        half=term.half,
        starts_on=term.starts_on,
        ends_on=term.ends_on,
        bells=list(term.bells),
        non_study_days=sorted(term.non_study_days),
        moved_days=sorted(term.moved_days, key=lambda moved: moved.date),
        control_periods=term.control_periods,
        is_current=is_current,
    )


def term_list(terms: Sequence[Term], today: dt.date) -> list[TermData]:
    """Return all terms, flagging the current one."""
    current = pick_current_term(terms, today)
    ordered = sorted(terms, key=lambda term: term.starts_on)
    return [
        term_data(t, is_current=bool(current and t.id == current.id)) for t in ordered
    ]
