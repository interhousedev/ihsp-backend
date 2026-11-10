"""Work-offs that an approved excuse creates for the lessons it covers."""

from collections.abc import Callable, Iterable
from uuid import UUID

from app.modules.academic.application.excuses.ports import ExcuseUnitOfWork
from app.modules.academic.domain.classwork.work_off import ResolvedWorkOff
from app.modules.academic.domain.excuses.excuse import Excuse
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries

TextFor = Callable[[str], str]


class ExcuseWorkOffs:
    """One work-off per covered lesson that has none yet; a teacher's task stays."""

    def __init__(
        self, *, schedule: ScheduleQueries, text_for: TextFor, clock: Clock
    ) -> None:
        """Store the schedule, the localized task text and the clock."""
        self.schedule = schedule
        self.text_for = text_for
        self.clock = clock

    async def for_excuse(
        self, uow: ExcuseUnitOfWork, excuse: Excuse, *, locale: str, assigned_by: UUID
    ) -> int:
        """Create work-offs for the lessons already held; return how many."""
        today = local_today(self.clock)
        end = min(excuse.ends_on or today, today)
        if end < excuse.starts_on:
            return 0
        lessons = await self.schedule.lessons_for_student(
            excuse.student_id, excuse.starts_on, end
        )
        covered = [
            lesson.id
            for lesson in lessons
            if lesson.status == "scheduled"
            and excuse.covers(lesson.date, lesson.id, lesson.subject_id)
        ]
        return await self.for_lessons(
            uow,
            excuse.student_id,
            covered,
            locale=locale,
            assigned_by=assigned_by,
        )

    async def for_lessons(
        self,
        uow: ExcuseUnitOfWork,
        student_id: UUID,
        lesson_ids: Iterable[UUID],
        *,
        locale: str,
        assigned_by: UUID,
    ) -> int:
        """Create the missing work-offs of the student for these lessons."""
        ids = list(lesson_ids)
        if not ids:
            return 0
        existing = {
            w.lesson_id
            for w in await uow.work_offs.for_lessons(ids)
            if w.student_id == student_id
        }
        now = self.clock.now()
        text = self.text_for(locale)
        created = 0
        for lesson_id in ids:
            if lesson_id in existing:
                continue
            await uow.work_offs.upsert(
                lesson_id=lesson_id,
                student_id=student_id,
                assigned_by=assigned_by,
                resolved=ResolvedWorkOff(text=text, template_id=None, due_date=None),
                at=now,
            )
            created += 1
        return created
