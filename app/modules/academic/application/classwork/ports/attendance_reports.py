"""Port: attendance aggregates (ACA-12, ACA-20)."""

import datetime as dt
from collections.abc import Sequence
from typing import Literal, Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.records import (
    ReportRow,
    StudentAttendanceData,
)

GroupView = Literal["student", "subject", "day", "lesson"]
AdminView = Literal["group", "student", "subject", "teacher"]


class AttendanceReports(Protocol):
    """Counts over the roster and absent arrays of lessons."""

    async def student_attendance(
        self,
        student_id: UUID,
        keys: Sequence[str],
        start: dt.date,
        end: dt.date,
        now: dt.datetime,
    ) -> StudentAttendanceData:
        """A student's own absences per subject, per day and the missed lessons."""
        ...

    async def absence_count(
        self, student_id: UUID, start: dt.date, end: dt.date
    ) -> int:
        """Number of lessons the student was absent from between two dates."""
        ...

    async def group_report(
        self,
        group_id: UUID,
        view: GroupView,
        start: dt.date,
        end: dt.date,
        now: dt.datetime,
    ) -> list[ReportRow]:
        """The curator's view of one group."""
        ...

    async def admin_report(
        self,
        view: AdminView,
        start: dt.date,
        end: dt.date,
        group_id: UUID | None,
        now: dt.datetime,
    ) -> list[ReportRow]:
        """The Administration's view."""
        ...
