"""Control weeks that a subject has not given a date to (derived, never stored)."""

import datetime as dt
from collections.abc import Collection, Mapping
from uuid import UUID

from app.modules.academic.application.assessments.ports.repositories import (
    ANY_STATUS,
    AssessmentQuery,
    AssessmentReader,
    AssessmentRepository,
)
from app.modules.academic.domain.assessments.periods import (
    TermControls,
    UndatedControl,
    undated_controls,
)

BIG = 20000


async def undated_for_groups(
    reader: AssessmentReader,
    assessments: AssessmentRepository,
    curricula: Mapping[UUID, Collection[UUID]],
    *,
    since: dt.date | None = None,
    until: dt.date | None = None,
    terms: list[TermControls] | None = None,
) -> list[UndatedControl]:
    """Return the control weeks overlapping [since, until] with no control yet.

    Every group's curriculum subject lacks a control for a week when no stored
    control, whatever its status, names that week for the group.
    """
    found_terms = await reader.terms() if terms is None else terms
    wanted = [
        t
        for t in found_terms
        if (since is None or t.ends_on >= since)
        and (until is None or t.starts_on <= until)
    ]
    if not wanted or not curricula:
        return []
    existing = await assessments.find(
        AssessmentQuery(
            since=min(t.starts_on for t in wanted),
            until=max(t.ends_on for t in wanted),
            statuses=ANY_STATUS,
            limit=BIG,
        )
    )
    found: list[UndatedControl] = []
    for group_id, subject_ids in curricula.items():
        found.extend(
            undated_controls(
                wanted,
                subject_ids=subject_ids,
                group_id=group_id,
                existing=existing,
                since=since or dt.date.min,
                until=until or dt.date.max,
            )
        )
    return found
