"""Rules of assessments: countdown, reminders, status changes and duplicates."""

import datetime as dt
from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.assessments.records import (
    Assessment,
    AssessmentSource,
    AssessmentStatus,
)


class _Control(Protocol):
    """What the duplicate rule looks at in a stored or a new control."""

    @property
    def subject_id(self) -> UUID:
        """The subject."""
        ...

    @property
    def kind(self) -> str:
        """The kind."""
        ...

    @property
    def audience(self) -> tuple[str, ...]:
        """The audience keys."""
        ...

    @property
    def date(self) -> dt.date:
        """The day."""
        ...

    @property
    def control(self) -> str | None:
        """The control week it belongs to."""
        ...


REMINDER_OFFSETS: tuple[int, ...] = (7, 3, 1)
DUPLICATE_WINDOW_DAYS = 7
SAME_CONTROL_WINDOW_DAYS = 60


def days_left(day: dt.date, today: dt.date) -> int:
    """Return the days from today to the control; negative once it is past."""
    return (day - today).days


def reminder_offset(assessment: Assessment, today: dt.date) -> int | None:
    """Return 7, 3 or 1 when a reminder is due today, else None.

    Only confirmed controls are reminded: a date nobody confirmed may be wrong, and
    a wrong reminder costs more trust than a missing one.
    """
    if assessment.status != "planned":
        return None
    left = days_left(assessment.date, today)
    return left if left in REMINDER_OFFSETS else None


def initial_status(source: AssessmentSource) -> AssessmentStatus:
    """Teachers and Administration plan a control; EMIS and students only suggest."""
    return "planned" if source in ("teacher", "admin") else "tentative"


def status_after_edit(
    current: AssessmentStatus, requested: AssessmentStatus | None, *, changed: bool
) -> AssessmentStatus:
    """Return the status after a staff edit.

    An explicit status wins (confirm with ``planned``, dismiss with ``cancelled``).
    Changing a tentative control confirms it: whoever fixed the date vouches for it.
    """
    if requested is not None:
        return requested
    if current == "tentative" and changed:
        return "planned"
    return current


def audiences_overlap(first: Iterable[str], second: Iterable[str]) -> bool:
    """Return True when some student belongs to both audiences.

    A group key covers its subgroups; two different subgroups do not overlap.
    """
    left = [audience_keys.parse(k) for k in first]
    right = [audience_keys.parse(k) for k in second]
    return any(
        group == other_group and (sub is None or other_sub is None or sub == other_sub)
        for group, sub in left
        for other_group, other_sub in right
    )


def is_duplicate(candidate: _Control, existing: _Control) -> bool:
    """Return True when ``existing`` already covers the candidate.

    Same subject and kind, an overlapping audience, and either the same control week
    (within a term's length) or a date within a week: the control is already known,
    whatever its status (a cancelled one stays dismissed).
    """
    if existing.subject_id != candidate.subject_id or existing.kind != candidate.kind:
        return False
    if not audiences_overlap(existing.audience, candidate.audience):
        return False
    apart = abs((existing.date - candidate.date).days)
    if candidate.control is not None and candidate.control == existing.control:
        return apart <= SAME_CONTROL_WINDOW_DAYS
    return apart <= DUPLICATE_WINDOW_DAYS
