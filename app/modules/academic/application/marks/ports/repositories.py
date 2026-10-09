"""Repository protocols the marks use cases depend on."""

import datetime as dt
from collections.abc import Collection, Sequence
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.marks.read_models import (
    AttendanceCount,
    LessonRow,
    MarkRow,
    ResultRow,
    StudentContext,
    SubjectInfo,
)
from app.modules.academic.domain.marks.records import (
    NewMark,
    ResultSnapshot,
    StoredMark,
    SyncRunRecord,
)
from app.modules.academic.domain.marks.sync import StudentSyncState


class StudentSyncRepository(Protocol):
    """Sync fields and curriculum of students."""

    async def lock(self, user_id: UUID) -> None:
        """Serialize two syncs of one student until the transaction ends."""
        ...

    async def get_state(self, user_id: UUID) -> StudentSyncState | None:
        """Return the student's sync state or None."""
        ...

    async def list_sync_candidates(self) -> list[UUID]:
        """Return active students whose backfill is done."""
        ...

    async def list_sync_members(self) -> list[tuple[UUID, UUID, int | None]]:
        """Return (user id, group id, subgroup) of the same students."""
        ...

    async def record_success(
        self, user_id: UUID, *, at: dt.datetime, backfilled: bool
    ) -> None:
        """Set synced_at, clear failures and (for a backfill) set backfilled_at."""
        ...

    async def record_failure(self, user_id: UUID, *, error: str) -> None:
        """Count one more consecutive failure and keep the error text."""
        ...

    async def touch_profile_synced(self, user_id: UUID, *, at: dt.datetime) -> None:
        """Remember when the profile was refreshed."""
        ...

    async def sync_failures(self, user_id: UUID) -> int:
        """Return the student's consecutive failed syncs (0 for an unknown student)."""
        ...


class MarksRepository(Protocol):
    """Marks written by the sync."""

    async def list_for_subject(
        self, student_id: UUID, subject_id: UUID, semester: int
    ) -> list[StoredMark]:
        """Return stored marks of one subject and semester, removed ones too."""
        ...

    async def add(self, marks: Sequence[NewMark]) -> None:
        """Insert new marks."""
        ...

    async def set_removed(
        self, mark_ids: Collection[UUID], removed_at: dt.datetime | None
    ) -> None:
        """Mark rows removed (a moment) or restored (None)."""
        ...

    async def values_by_type(
        self, student_id: UUID, subject_id: UUID, semester: int
    ) -> dict[str, list[int]]:
        """Return non-removed mark values of a subject grouped by type."""
        ...

    async def semester_values(self, student_id: UUID, semester: int) -> list[int]:
        """Return all non-removed mark values of the semester."""
        ...


class ResultsRepository(Protocol):
    """Current results."""

    async def get(
        self, student_id: UUID, semester: int, subject_id: UUID | None
    ) -> ResultSnapshot | None:
        """Return a subject result, or the GPA row for subject_id None."""
        ...

    async def save(
        self,
        student_id: UUID,
        semester: int,
        subject_id: UUID | None,
        snapshot: ResultSnapshot,
    ) -> None:
        """Insert or update a result row."""
        ...


class LessonMatcher(Protocol):
    """Finds the lesson a mark belongs to (ACA-14)."""

    async def match(
        self,
        *,
        group_id: UUID,
        subgroup: int | None,
        pairs: Collection[tuple[UUID, dt.date]],
    ) -> dict[tuple[UUID, dt.date], UUID]:
        """Return the earliest lesson of the student's audience per (subject, date)."""
        ...


class SyncRunsRepository(Protocol):
    """Sync run summaries."""

    async def create(self, started_at: dt.datetime) -> UUID:
        """Insert a running run and return its id."""
        ...

    async def finish(
        self,
        run_id: UUID,
        *,
        finished_at: dt.datetime,
        status: str,
        stats: dict[str, int],
    ) -> None:
        """Close a run with its status and statistics."""
        ...

    async def running_since(self, cutoff: dt.datetime) -> bool:
        """Return True if a run started after the cutoff is still running."""
        ...

    async def list_page(
        self, *, before: tuple[dt.datetime, UUID] | None, limit: int
    ) -> list[SyncRunRecord]:
        """Return runs newest first, after the cursor position."""
        ...


class MarksReader(Protocol):
    """Read queries behind the student-facing marks views."""

    async def student_context(self, user_id: UUID) -> StudentContext | None:
        """Return the student with group data, or None."""
        ...

    async def subjects(self, subject_ids: Collection[UUID]) -> dict[UUID, SubjectInfo]:
        """Return subjects by id."""
        ...

    async def results(self, student_id: UUID, semester: int | None) -> list[ResultRow]:
        """Return result rows of one semester or of all semesters."""
        ...

    async def marks(
        self,
        student_id: UUID,
        *,
        semester: int | None = None,
        subject_id: UUID | None = None,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> list[MarkRow]:
        """Return non-removed marks, newest date first."""
        ...

    async def new_marks(
        self, student_id: UUID, since: dt.datetime | None, limit: int
    ) -> list[MarkRow]:
        """Return non-removed marks first seen after a moment, newest first."""
        ...

    async def lessons(
        self,
        ctx: StudentContext,
        *,
        subject_id: UUID | None = None,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> list[LessonRow]:
        """Return the student's lessons by audience, ordered by date and period."""
        ...

    async def next_lessons(
        self, ctx: StudentContext, subject_ids: Collection[UUID], after: dt.datetime
    ) -> dict[UUID, LessonRow]:
        """Return the next scheduled lesson per subject that ends after a moment."""
        ...

    async def attendance_counts(
        self, student_id: UUID, start: dt.date | None, end: dt.date | None
    ) -> dict[UUID, AttendanceCount]:
        """Return absences and counted lessons per subject."""
        ...

    async def teacher_ids(
        self,
        ctx: StudentContext,
        subject_ids: Collection[UUID],
        start: dt.date | None,
        end: dt.date | None,
    ) -> dict[UUID, list[UUID]]:
        """Return the teachers who taught each subject to the student's audience."""
        ...

    async def group_names(self, group_ids: Collection[UUID]) -> dict[UUID, str]:
        """Return group names by id."""
        ...

    async def terms(self) -> list[tuple[dt.date, dt.date]]:
        """Return the dates of every term."""
        ...

    async def gpa_values(
        self, user_ids: Sequence[UUID], semester: int | None
    ) -> dict[UUID, Decimal | None]:
        """Return the GPA of each student (their current semester if None)."""
        ...
