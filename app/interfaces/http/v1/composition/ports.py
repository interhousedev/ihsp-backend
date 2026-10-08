"""Local ports of the composition endpoints.

The cross-module contracts in `app.shared.contracts` do not cover everything the
composed pages show. What they lack is declared here, one small port per provider
module. Bootstrap (I1) implements each port over the provider's use cases and passes
the objects to `build_composition` through `CompositionPorts`.

Results are JSON-shaped dicts named after the types of the API contract
(§ API contract -> Schemas): field names and nesting are exactly those of the type, so
the response models validate them as they are. Ports that read a user's own pages
(`StudentViews`, `TeacherViews`) take the user id; their adapters run the module's
use cases as that user (read-only).
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor

# JSON-shaped object of the API contract; the keys are those of the named type.
JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class DayCounts:
    """Lesson counts of one day over all groups (ADM-2).

    `lessons` counts every lesson of the day, cancelled ones included; `cancelled`
    is the cancelled subset; `teacher_needed` counts scheduled lessons that have no
    teacher.
    """

    lessons: int
    cancelled: int
    teacher_needed: int


class FilesViews(Protocol):
    """File facts the contract `FilesApi` lacks (provider: files)."""

    async def expiry_dates(self, owner_id: UUID, until: dt.date) -> list[dt.date]:
        """Return `expires_on` of the owner's ready files due on or before `until`.

        The list is sorted ascending; files without an expiry date are left out.
        """
        ...

    async def search_files(
        self, owner_id: UUID, query: str, limit: int
    ) -> list[JsonObject]:
        """Return `FileItem` dicts matching by name or by extracted text.

        Natural source: `FilesApi.search_text` plus a case-insensitive name match,
        built into `FileItem` like `GET /v1/me/files` does. At most `limit` items.
        """
        ...


class SyncViews(Protocol):
    """EMIS sync facts (provider: academic marks and sync)."""

    async def sync_failures(self, user_id: UUID) -> int:
        """Return the student's consecutive failed syncs (`students.sync_failures`)."""
        ...

    async def last_sync_run(self, actor: Actor) -> JsonObject | None:
        """Return the newest `SyncRunItem` or None when no run exists yet.

        Natural source: `ListSyncRuns.execute(actor, None, 1)`.
        """
        ...


class CalendarTokenStore(Protocol):
    """Secret iCal feed tokens (provider: academic schedule, WEB-6).

    The column is `academic.students.calendar_token_hash`; only the SHA-256 of the
    token is stored.
    """

    async def rotate(self, user_id: UUID, token_hash: str) -> bool:
        """Replace the student's token hash; the old URL stops working.

        Returns False when the user has no student record.
        """
        ...

    async def user_for_token(self, token_hash: str) -> UUID | None:
        """Return the active student that owns the token hash."""
        ...


class ScheduleOverview(Protocol):
    """School-wide schedule facts (provider: academic schedule)."""

    async def term_bounds(self, day: dt.date) -> tuple[dt.date, dt.date] | None:
        """Return (starts_on, ends_on) of the term that applies on `day`.

        Natural source: `CurrentTerm.execute(day)` (the term containing the day, else
        the next, else the last). None when no term exists.
        """
        ...

    async def day_counts(self, actor: Actor, day: dt.date) -> DayCounts:
        """Return the lesson counts of `day` (natural source: `ListLessons`)."""
        ...

    async def active_group_ids(self) -> list[UUID]:
        """Return the ids of the active groups (natural source: `ListGroups`)."""
        ...


class AttendanceStats(Protocol):
    """Attendance aggregates (provider: academic classwork)."""

    async def group_absence_rates(
        self, actor: Actor, start: dt.date, end: dt.date
    ) -> dict[UUID, float | None]:
        """Return the absence rate per group between two dates.

        The rate is the `rate` of the rows of `AttendanceReport` with `view=group`:
        absences divided by lessons with taken attendance (0..1), None when no
        lesson had attendance. A group without a row is simply absent.
        """
        ...


class StudentViews(Protocol):
    """A student's own pages, for the read-only admin view (provider: academic).

    Natural sources, run as the student: `GetStudentProfile`, `GetStudentTimetable`,
    `GetSemesterGrades` and the student attendance use case.
    """

    async def profile(self, user_id: UUID) -> JsonObject:
        """Return `StudentProfile`."""
        ...

    async def timetable(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[JsonObject]:
        """Return the student's `LessonItem` list between two dates."""
        ...

    async def grades(self, user_id: UUID) -> JsonObject:
        """Return `SemesterGrades` of the current semester."""
        ...

    async def attendance(self, user_id: UUID) -> JsonObject:
        """Return `StudentAttendance` for the current term (keys `from` and `to`)."""
        ...


class TeacherViews(Protocol):
    """A teacher's pages, for the admin view (provider: academic)."""

    async def timetable(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[JsonObject]:
        """Return the `LessonItem` list the teacher teaches between two dates."""
        ...

    async def missing_attendance(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[JsonObject]:
        """Return finished lessons of the teacher without attendance (`LessonItem`)."""
        ...

    async def curated_groups(self, teacher_id: UUID) -> list[JsonObject]:
        """Return the `GroupItem` list of the groups the teacher curates."""
        ...


class AccountViews(Protocol):
    """Account detail for administrators (provider: identity)."""

    async def account(
        self, actor: Actor, user_id: UUID, *, ip: str | None, user_agent: str | None
    ) -> JsonObject:
        """Return `AdminUserDetail` (the user plus Telegram, sessions, recent audit).

        Natural source: `GetUserDetail`, which itself records the audit event
        `student.viewed` when the account is a student's, so callers never audit again.
        """
        ...


class BroadcastViews(Protocol):
    """Broadcasts for the dashboard (provider: admin)."""

    async def scheduled(self, actor: Actor, limit: int) -> list[JsonObject]:
        """Return `BroadcastItem` dicts with status `scheduled`, soonest first."""
        ...


@dataclass(frozen=True, slots=True)
class CompositionPorts:
    """Everything `build_composition` needs beyond the cross-module contracts."""

    files: FilesViews
    sync: SyncViews
    calendar_tokens: CalendarTokenStore
    schedule_overview: ScheduleOverview
    attendance_stats: AttendanceStats
    students: StudentViews
    teachers: TeacherViews
    accounts: AccountViews
    broadcasts: BroadcastViews
