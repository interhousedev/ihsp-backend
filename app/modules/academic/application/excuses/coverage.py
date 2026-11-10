"""Excuse coverage of a lesson, as the attendance use cases need it."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.excuses.ports import ExcuseUowFactory
from app.modules.academic.domain.classwork.excuse_ref import (
    ExcuseRef,
    effective_excuses,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.excuses.excuse import Excuse


class ExcuseCoverageQuery:
    """Approved excuses that include a lesson by date, lesson or subject."""

    def __init__(self, *, uow_factory: ExcuseUowFactory) -> None:
        """Store the transaction factory."""
        self.uow_factory = uow_factory

    async def covering(
        self, lesson: Lesson, student_ids: Sequence[UUID]
    ) -> dict[UUID, ExcuseRef]:
        """Map each covered student of ``student_ids`` to the covering excuse."""
        if not student_ids:
            return {}
        async with self.uow_factory() as uow:
            found = await uow.excuses.covering(student_ids, lesson.date)
            codes = {
                t.id: t.code for t in await uow.excuses.templates(active_only=False)
            }
        covered: dict[UUID, ExcuseRef] = {}
        for excuse in found:
            if excuse.covers(lesson.date, lesson.id, lesson.subject_id):
                covered.setdefault(
                    excuse.student_id,
                    ExcuseRef(
                        excuse.id,
                        codes.get(excuse.template_id, ""),
                        str(excuse.origin),
                    ),
                )
        return covered

    async def effective(
        self, lessons: Sequence[Lesson]
    ) -> dict[UUID, dict[UUID, ExcuseRef]]:
        """Excused absences per lesson: marks plus approved excuses (a query a day)."""
        absent_by_day: dict[dt.date, set[UUID]] = {}
        for lesson in lessons:
            if lesson.attendance_absent:
                absent_by_day.setdefault(lesson.date, set()).update(
                    lesson.attendance_absent
                )
        found: dict[dt.date, list[Excuse]] = {}
        codes: dict[UUID, str] = {}
        if absent_by_day:
            async with self.uow_factory() as uow:
                codes = {
                    t.id: t.code for t in await uow.excuses.templates(active_only=False)
                }
                for day, students in absent_by_day.items():
                    found[day] = await uow.excuses.covering(sorted(students), day)
        result: dict[UUID, dict[UUID, ExcuseRef]] = {}
        for lesson in lessons:
            covered: dict[UUID, ExcuseRef] = {}
            for excuse in found.get(lesson.date, ()):
                if excuse.covers(lesson.date, lesson.id, lesson.subject_id):
                    covered.setdefault(
                        excuse.student_id,
                        ExcuseRef(
                            excuse.id,
                            codes.get(excuse.template_id, ""),
                            str(excuse.origin),
                        ),
                    )
            result[lesson.id] = effective_excuses(
                lesson.attendance_absent, lesson.attendance_excused, covered
            )
        return result
