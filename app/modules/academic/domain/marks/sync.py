"""Records and enums of one student's EMIS sync."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.shared.contracts.emis import EmisSubjectRatings

SyncMode = Literal["regular", "backfill", "profile"]
SyncStatus = Literal["ok", "skipped", "left", "reauth"]
SyncSlot = Literal["11:30", "15:00", "20:00", "manual"]

ALL_SEMESTERS = (1, 2, 3, 4)


@dataclass(slots=True)
class SyncCounters:
    """Request and mark counters a run coordinator reads after the students ran."""

    emis_requests: int = 0
    marks_new: int = 0


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """How one student's sync ended without raising."""

    user_id: UUID
    status: SyncStatus


@dataclass(frozen=True, slots=True)
class SyncSubject:
    """A subject of the student's curriculum that EMIS knows."""

    subject_id: UUID
    emis_subject_id: int
    name: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class StudentSyncState:
    """What the sync needs to know about a student before calling EMIS."""

    user_id: UUID
    group_id: UUID
    subgroup: int | None
    status: Literal["active", "left"]
    backfilled_at: datetime | None
    current_semester: int | None
    subjects: tuple[SyncSubject, ...]


@dataclass(frozen=True, slots=True)
class FetchedRatings:
    """One subject's EMIS response for one semester."""

    subject: SyncSubject
    ratings: EmisSubjectRatings


def semesters_for(mode: SyncMode, current_semester: int | None) -> tuple[int, ...]:
    """Semesters to fetch: all four for a backfill, the current one otherwise."""
    if mode == "backfill":
        return ALL_SEMESTERS
    return () if current_semester is None else (current_semester,)
