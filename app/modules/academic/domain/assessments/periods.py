"""Control weeks of a term (set by Administration) and the controls they imply.

A semester has two midterm controls and one final control. Administration sets the
week of each per term; a subject then gets its own date from a teacher or from EMIS.
Until it does, the week itself stands in for the date.
"""

import datetime as dt
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.assessments.records import (
    Assessment,
    AssessmentKind,
)
from app.modules.academic.domain.assessments.rules import audiences_overlap
from app.modules.academic.domain.schedule.term import (
    CONTROL_NAMES,
    ControlName,
    ControlPeriod,
    ControlPeriods,
)

CONTROL_KINDS: dict[ControlName, AssessmentKind] = {
    "midterm_1": "midterm",
    "midterm_2": "midterm",
    "final": "final",
}


@dataclass(frozen=True, slots=True)
class TermControls:
    """A term with its control weeks."""

    term_id: UUID
    starts_on: dt.date
    ends_on: dt.date
    periods: ControlPeriods

    def contains(self, day: dt.date) -> bool:
        """Return True if the day lies inside the term."""
        return self.starts_on <= day <= self.ends_on


@dataclass(frozen=True, slots=True)
class UndatedControl:
    """A control week that a subject has not given a date to yet.

    It is derived from the term, never stored, so changing the week moves it.
    """

    id: UUID
    term_id: UUID
    control: ControlName
    kind: AssessmentKind
    subject_id: UUID
    group_id: UUID
    period: ControlPeriod

    def date(self, today: dt.date) -> dt.date:
        """Return the day to count down to: the week's start, or today while it runs."""
        if self.period.start < today <= self.period.end:
            return today
        return self.period.start

    @property
    def audience(self) -> tuple[str, ...]:
        """The whole group."""
        return (audience_keys.key(self.group_id, None),)


def undated_id(
    term_id: UUID, control: ControlName, subject_id: UUID, group_id: UUID
) -> UUID:
    """Return the stable id of an undated control (the page opens it by this id)."""
    return uuid5(
        NAMESPACE_URL, f"ihsp:undated:{term_id}:{control}:{subject_id}:{group_id}"
    )


def control_on(
    kind: AssessmentKind, day: dt.date, terms: Iterable[TermControls]
) -> ControlName | None:
    """Return the control week of that kind that holds the day, if any."""
    for term in terms:
        for name, period in term.periods.items():
            if CONTROL_KINDS[name] == kind and period.start <= day <= period.end:
                return name
    return None


def infer_control(
    kind: AssessmentKind, day: dt.date, terms: Sequence[TermControls]
) -> ControlName | None:
    """Return the control week a dated control belongs to.

    The week that holds the day, else the nearest week of that kind in the term the
    day falls in. None for ``other``, or when the term has no such week.
    """
    inside = control_on(kind, day, terms)
    if inside is not None or kind == "other":
        return inside
    term = next((t for t in terms if t.contains(day)), None)
    if term is None:
        return None
    candidates = [
        (min(abs((day - period.start).days), abs((day - period.end).days)), index, name)
        for index, (name, period) in enumerate(term.periods.items())
        if CONTROL_KINDS[name] == kind
    ]
    return min(candidates)[2] if candidates else None


def period_of(
    control: ControlName | None, day: dt.date, terms: Iterable[TermControls]
) -> ControlPeriod | None:
    """Return the week of a control in the term that holds the day."""
    if control is None:
        return None
    term = next((t for t in terms if t.contains(day)), None)
    return None if term is None else term.periods.get(control)


def undated_controls(
    terms: Iterable[TermControls],
    *,
    subject_ids: Collection[UUID],
    group_id: UUID,
    existing: Sequence[Assessment],
    since: dt.date,
    until: dt.date,
) -> list[UndatedControl]:
    """Return the control weeks in [since, until] that some subject has no control for.

    A subject has one when any stored control of the group (whatever its status: a
    cancelled one means the control does not happen) names that control week.
    """
    group_keys = (audience_keys.key(group_id, None),)
    found: list[UndatedControl] = []
    for term in terms:
        for name, period in term.periods.items():
            if period.end < since or period.start > until:
                continue
            taken = {
                a.subject_id
                for a in existing
                if a.control == name
                and term.contains(a.date)
                and audiences_overlap(a.audience, group_keys)
            }
            found.extend(
                UndatedControl(
                    id=undated_id(term.term_id, name, subject_id, group_id),
                    term_id=term.term_id,
                    control=name,
                    kind=CONTROL_KINDS[name],
                    subject_id=subject_id,
                    group_id=group_id,
                    period=period,
                )
                for subject_id in sorted(set(subject_ids) - taken, key=str)
            )
    order = {name: i for i, name in enumerate(CONTROL_NAMES)}
    return sorted(
        found, key=lambda c: (c.period.start, order[c.control], str(c.subject_id))
    )
