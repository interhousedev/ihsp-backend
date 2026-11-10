"""Excuse coverage of a lesson, as the attendance use cases need it."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.excuses.ports import ExcuseUowFactory
from app.modules.academic.domain.classwork.excuse_ref import ExcuseRef
from app.modules.academic.domain.classwork.lesson import Lesson


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
