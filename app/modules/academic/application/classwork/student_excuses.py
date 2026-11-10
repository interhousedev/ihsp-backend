"""Use case: the excuses of the student's absences in a range (schedule day)."""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.ports.excuse_coverage import (
    ExcuseCoverage,
)
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)


class StudentExcuses:
    """The ``ExcuseRef`` of every excused lesson of one student, by lesson id."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        excuse_coverage: ExcuseCoverage,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.excuse_coverage = excuse_coverage

    async def execute(
        self, student_id: UUID, start: dt.date, end: dt.date
    ) -> dict[UUID, dict[str, Any]]:
        """Return ``{lesson_id: ExcuseRef dict}`` for lessons excused in the range."""
        async with self.uow_factory() as uow:
            missed = await uow.lesson_reader.student_absences(student_id, start, end)
        effective = await self.excuse_coverage.effective(missed)
        return {
            lesson_id: refs[student_id].as_dict()
            for lesson_id, refs in effective.items()
            if student_id in refs
        }
