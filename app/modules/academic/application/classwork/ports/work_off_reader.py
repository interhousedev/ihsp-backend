"""Port: work-off read models for students, teachers and administrators."""

import datetime as dt
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.work_off_views import (
    GroupBy,
    StatRow,
    WorkOffFilter,
    WorkOffView,
)


class WorkOffReader(Protocol):
    """Work-offs joined with lessons and groups."""

    async def for_student(self, student_id: UUID, open_only: bool) -> list[WorkOffView]:
        """The student's work-offs, newest lesson first."""
        ...

    async def open_for_teacher(self, teacher_id: UUID) -> list[WorkOffView]:
        """Open work-offs the teacher assigned or whose lesson they teach."""
        ...

    async def admin_list(
        self, flt: WorkOffFilter, limit: int, offset: int
    ) -> tuple[int, list[WorkOffView]]:
        """Filtered page, newest lesson first, and the total count."""
        ...

    async def stats(
        self, group_by: GroupBy, start: dt.date, end: dt.date
    ) -> list[StatRow]:
        """Open and done counts per key for lessons in the date range."""
        ...
