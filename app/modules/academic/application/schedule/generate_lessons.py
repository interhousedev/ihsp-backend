"""Generate lessons from the timetable for the next days (UF-SYS-05, ACA-7)."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.schedule.common import (
    UowFactory,
    kick_recompute_due_dates,
    today,
)
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.room_cache import (
    invalidate_room_pages,
)
from app.modules.academic.domain.schedule.generation import (
    GenerationPlan,
    plan_generation,
)
from app.modules.academic.domain.schedule.term import Term
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_DAYS = 14


class GenerateLessons:
    """Expand timetable entries into lessons and keep them up to date."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        kicker: TaskKicker,
        cache: RoomPageCache,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker
        self.cache = cache

    async def execute(
        self,
        *,
        term_id: UUID | None = None,
        from_date: dt.date | None = None,
        days: int = DEFAULT_DAYS,
    ) -> int:
        """Generate for every term overlapping the window; return changed lessons."""
        start = from_date or today(self.clock)
        end = start + dt.timedelta(days=days - 1)
        async with self.uow_factory() as uow:
            terms = await uow.terms.overlapping(start, end, exclude_id=None)
        total = 0
        for term in terms:
            if term_id is None or term.id == term_id:
                total += await self._generate_term(term.id, start, end)
        return total

    async def _generate_term(self, term_id: UUID, start: dt.date, end: dt.date) -> int:
        now = self.clock.now()
        async with self.uow_factory() as uow:
            await uow.lock_term(term_id)
            term = await uow.terms.get(term_id)
            if term is None:
                return 0
            entries = await uow.entries.list_for_term(term.id)
            existing = await uow.lessons.generated_in_range(term.id, start, end)
            plan = plan_generation(
                term, entries, existing, start=start, end=end, now=now
            )
            changed = await self._apply(uow, plan)
            self._log_missing_bells(term, plan)
            kick_recompute_due_dates(uow, self.kicker, changed)
            await invalidate_room_pages(
                uow,
                self.cache,
                [lesson.room_id for lesson in plan.inserts + plan.updates],
            )
            await uow.commit()
        return len(changed)

    @staticmethod
    async def _apply(uow: ScheduleUnitOfWork, plan: GenerationPlan) -> list[UUID]:
        changed: list[UUID] = []
        for lesson in plan.inserts:
            if await uow.lessons.try_add(lesson):
                changed.append(lesson.id)
            else:
                logger.warning("lesson_insert_conflict", lesson_id=str(lesson.id))
        for lesson in plan.updates:
            if await uow.lessons.try_save(lesson):
                changed.append(lesson.id)
            else:
                logger.warning("lesson_update_conflict", lesson_id=str(lesson.id))
        for lesson in plan.cancels:
            await uow.lessons.save(lesson)
            changed.append(lesson.id)
        if plan.deletes:
            await uow.lessons.delete_many([lesson.id for lesson in plan.deletes])
            changed.extend(lesson.id for lesson in plan.deletes)
        return changed

    @staticmethod
    def _log_missing_bells(term: Term, plan: GenerationPlan) -> None:
        for entry_id in plan.missing_bells:
            logger.warning(
                "entry_without_bell", term_id=str(term.id), entry_id=str(entry_id)
            )
