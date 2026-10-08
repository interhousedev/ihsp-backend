"""Builders shared by the schedule tests."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.entry_builder import EntryInput
from app.modules.academic.domain.schedule.term import Term
from app.shared.ids import new_id
from tests.academic.schedule.env import TERM_END, TERM_START, default_bells


def make_term(**kwargs: object) -> Term:
    """A term from Sep 1 to Dec 25 with the default bells."""
    fields: dict[str, object] = {
        "id": new_id(),
        "academic_year": "2026-2027",
        "half": 1,
        "starts_on": TERM_START,
        "ends_on": TERM_END,
        "bells": default_bells(),
    }
    fields.update(kwargs)
    return Term(**fields)  # type: ignore[arg-type]


def entry_input(
    term_id: UUID,
    subject_id: UUID,
    group_id: UUID,
    *,
    subgroup: int | None = None,
    weekday: int = 1,
    period: int = 1,
    teacher_id: UUID | None = None,
    room_name: str | None = None,
    parity: Any = "every",
    valid_to: dt.date | None = None,
) -> EntryInput:
    """An entry request for one group (or subgroup)."""
    return EntryInput(
        term_id=term_id,
        weekday=weekday,
        period=period,
        week_parity=parity,
        subject_id=subject_id,
        teacher_id=teacher_id,
        room_name=room_name,
        audience=[(group_id, subgroup)],
        valid_from=dt.date(2026, 9, 1),
        valid_to=valid_to,
    )
