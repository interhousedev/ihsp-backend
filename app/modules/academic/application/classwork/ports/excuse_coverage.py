"""Port: which students of a lesson are covered by an approved excuse."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.excuse_ref import ExcuseRef
from app.modules.academic.domain.classwork.lesson import Lesson


class ExcuseCoverage(Protocol):
    """Provided by the excuses use cases; attendance reads it to lock entries."""

    async def covering(
        self, lesson: Lesson, student_ids: Sequence[UUID]
    ) -> dict[UUID, ExcuseRef]:
        """Return ``{student_id: ExcuseRef}`` for covered students of the lesson."""
        ...

    async def effective(
        self, lessons: Sequence[Lesson]
    ) -> dict[UUID, dict[UUID, ExcuseRef]]:
        """Return ``{lesson_id: {student_id: ExcuseRef}}`` of the excused absences.

        The one rule of "excused": absent and (an excuse mark or an approved excuse
        that covers the lesson).
        """
        ...
