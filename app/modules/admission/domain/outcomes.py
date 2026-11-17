"""Self-reported application outcomes, their aggregates and deadline nudges."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.calendar import TASHKENT
from app.modules.admission.domain.documents import Deadline, confirmed_instant

OutcomeStatus = Literal[
    "applied", "accepted", "rejected", "waitlisted", "deferred", "enrolled"
]
OUTCOME_STATUSES: Final = (
    "applied",
    "accepted",
    "rejected",
    "waitlisted",
    "deferred",
    "enrolled",
)
OUTCOME_PLANS: Final = ("ed", "ed2", "ea", "rea", "rd", "rolling", "other")
ACCEPTED_STATUSES: Final = frozenset({"accepted", "enrolled"})
MIN_CYCLE: Final = 2000
MAX_CYCLE: Final = 2100

NudgeKind = Literal["d30", "d7", "d0", "result"]
RESULT_AFTER_DEADLINE_DAYS: Final = 60
"""Result question when no decision date is known."""
RESULT_WINDOW_DAYS: Final = 14
"""How long after its date the result question can still be sent."""
_OFFSET_OF: Final = {"d30": 30, "d7": 7}


@dataclass(slots=True)
class Outcome:
    """What a student reports about one application cycle at one institution."""

    id: UUID
    student_id: UUID
    institution_id: UUID
    cycle: int
    plan: str
    status: OutcomeStatus
    share_name: bool = False
    lock_version: int = 0
    updated_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class SharedName:
    """A student's name, shown only because they opted in (or staff looks)."""

    name: str
    status: str
    plan: str
    shared: bool


@dataclass(slots=True)
class OutcomeTally:
    """Counts for one institution and cycle."""

    institution_id: UUID
    cycle: int
    reported: int = 0
    accepted: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    names: list[SharedName] = field(default_factory=list)


def aggregate(
    outcomes: Iterable[Outcome],
    names: Mapping[UUID, str],
    *,
    reveal_all: bool = False,
) -> list[OutcomeTally]:
    """Tally outcomes per institution and cycle.

    Every report counts as an application; `accepted` also counts enrolled.
    A name is listed only when the student opted in (`share_name`), or when
    `reveal_all` is set (staff); `names` holds the resolved display names and
    a student without one is never listed.
    """
    tallies: dict[tuple[UUID, int], OutcomeTally] = {}
    for o in outcomes:
        tally = tallies.setdefault(
            (o.institution_id, o.cycle), OutcomeTally(o.institution_id, o.cycle)
        )
        tally.reported += 1
        tally.by_status[o.status] = tally.by_status.get(o.status, 0) + 1
        if o.status in ACCEPTED_STATUSES:
            tally.accepted += 1
        name = names.get(o.student_id)
        if name and (o.share_name or reveal_all):
            tally.names.append(SharedName(name, o.status, o.plan, o.share_name))
    for tally in tallies.values():
        tally.names.sort(key=lambda n: n.name.casefold())
    return sorted(
        tallies.values(), key=lambda t: (-t.cycle, -t.reported, str(t.institution_id))
    )


def revealed_students(outcomes: Iterable[Outcome], *, reveal_all: bool) -> set[UUID]:
    """Students whose names may be looked up for the aggregate."""
    return {o.student_id for o in outcomes if o.share_name or reveal_all}


# -- nudges -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NudgeTarget:
    """A student who follows an institution (list entry or catalog interest)."""

    student_id: UUID
    institution_id: UUID
    decision_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class Nudge:
    """One notification to send."""

    student_id: UUID
    institution_id: UUID
    cycle: int
    kind: NudgeKind
    days: int
    due_utc: dt.datetime
    dedupe_key: str

    @property
    def offset_days(self) -> int | None:
        """The reminder offset a student must have enabled, if any."""
        return _OFFSET_OF.get(self.kind)


def nudge_kind(now: dt.datetime, due: dt.datetime) -> NudgeKind | None:
    """Which pre-deadline nudge applies now (Tashkent calendar days)."""
    left = (due.astimezone(TASHKENT).date() - now.astimezone(TASHKENT).date()).days
    if left == 0:
        return "d0" if now <= due else None
    if left in (29, 30):
        return "d30"
    if left in (6, 7):
        return "d7"
    return None


def result_due(due: dt.datetime, decision_at: dt.datetime | None) -> dt.date:
    """The day the result is asked: after the decision date, else 60 days on."""
    if decision_at is not None:
        return decision_at.astimezone(TASHKENT).date() + dt.timedelta(days=1)
    return due.astimezone(TASHKENT).date() + dt.timedelta(
        days=RESULT_AFTER_DEADLINE_DAYS
    )


def _key(student: UUID, institution: UUID, cycle: int, tag: str) -> str:
    return f"admission-nudge:{student}:{institution}:{cycle}:{tag}"


def plan_nudges(
    now: dt.datetime,
    targets: Collection[NudgeTarget],
    deadlines: Iterable[Deadline],
    reported: Collection[tuple[UUID, UUID, int]],
) -> list[Nudge]:
    """Nudges due now; students who already reported the cycle get none.

    Pre-deadline nudges are per deadline round (`d30`, `d7`, `d0`); the result
    question is once per institution and cycle, counted from the latest round.
    """
    by_institution: dict[UUID, list[tuple[Deadline, dt.datetime]]] = defaultdict(list)
    for deadline in deadlines:
        due = confirmed_instant(deadline)
        if due is not None and deadline.superseded_by is None:
            by_institution[deadline.institution_id].append((deadline, due))
    today = now.astimezone(TASHKENT).date()
    out: list[Nudge] = []
    for target in targets:
        rounds = by_institution.get(target.institution_id, [])
        latest: dict[int, dt.datetime] = {}
        for deadline, due in rounds:
            latest[deadline.cycle] = max(latest.get(deadline.cycle, due), due)
            kind = nudge_kind(now, due)
            if (
                kind is None
                or (
                    target.student_id,
                    target.institution_id,
                    deadline.cycle,
                )
                in reported
            ):
                continue
            out.append(
                Nudge(
                    target.student_id,
                    target.institution_id,
                    deadline.cycle,
                    kind,
                    (due.astimezone(TASHKENT).date() - today).days,
                    due,
                    _key(
                        target.student_id,
                        target.institution_id,
                        deadline.cycle,
                        f"{deadline.id}:{kind}",
                    ),
                )
            )
        for cycle, due in latest.items():
            asked = result_due(due, target.decision_at)
            age = (today - asked).days
            if (
                0 <= age < RESULT_WINDOW_DAYS
                and now > due
                and (target.student_id, target.institution_id, cycle) not in reported
            ):
                out.append(
                    Nudge(
                        target.student_id,
                        target.institution_id,
                        cycle,
                        "result",
                        0,
                        due,
                        _key(target.student_id, target.institution_id, cycle, "result"),
                    )
                )
    return out
