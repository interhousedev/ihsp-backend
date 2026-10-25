"""Add an extra lesson on a date (UF-ADM-07, ACA-7)."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.common import (
    UowFactory,
    caller_locale,
    kick_recompute_due_dates,
)
from app.modules.academic.application.schedule.ensure_room import ensure_room_in
from app.modules.academic.application.schedule.lesson_items import build_lesson_items
from app.modules.academic.application.schedule.lesson_notifications import (
    notify_lesson_changed,
)
from app.modules.academic.application.schedule.lesson_slots import (
    check_subject_and_groups,
    raise_on_lesson_conflicts,
    slot_times,
)
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.room_cache import (
    invalidate_room_pages,
)
from app.modules.academic.domain.schedule.audience_display import keys_from_input
from app.modules.academic.domain.schedule.conflicts import LessonSlot
from app.modules.academic.domain.schedule.errors import (
    EntryInvalidError,
    LessonNotFoundError,
)
from app.modules.academic.domain.schedule.lesson import Lesson
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker


@dataclass(frozen=True, slots=True)
class ExtraLessonInput:
    """The fields of ExtraLessonInput in the API contract."""

    date: dt.date
    period: int
    subject_id: UUID
    teacher_id: UUID | None
    room_name: str | None
    audience: Sequence[tuple[UUID, int | None]]
    topic: str | None = None


class CreateExtraLesson:
    """Create a lesson that no timetable entry produces."""

    def __init__(
        self,
        uow_factory: UowFactory,
        reader: ScheduleReader,
        identity: IdentityDirectory,
        clock: Clock,
        kicker: TaskKicker,
        cache: RoomPageCache,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.reader = reader
        self.identity = identity
        self.clock = clock
        self.kicker = kicker
        self.cache = cache

    async def execute(self, actor: Actor, data: ExtraLessonInput) -> dict[str, Any]:
        """Insert the lesson after checking times and conflicts; return LessonItem."""
        if not data.audience or data.period < 1:
            raise EntryInvalidError(params={"reason": "audience"})
        locale = await caller_locale(self.identity, actor)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            term, starts_at, ends_at = await slot_times(uow, data.date, data.period)
            await uow.lock_term(term.id)
            subject = await check_subject_and_groups(
                uow, data.subject_id, {g for g, _ in data.audience}
            )
            room = (
                await ensure_room_in(uow, data.room_name, now)
                if data.room_name and data.room_name.strip()
                else None
            )
            lesson = Lesson(
                id=new_id(),
                term_id=term.id,
                date=data.date,
                period=data.period,
                starts_at=starts_at,
                ends_at=ends_at,
                subject_id=data.subject_id,
                teacher_id=data.teacher_id,
                room_id=room.id if room else None,
                audience=keys_from_input(data.audience),
                is_overridden=True,
                topic=(data.topic or "").strip() or None,
            )
            await raise_on_lesson_conflicts(
                uow,
                LessonSlot(
                    lesson.id,
                    starts_at,
                    ends_at,
                    lesson.teacher_id,
                    lesson.room_id,
                    lesson.audience,
                ),
            )
            await uow.lessons.add(lesson)
            await notify_lesson_changed(
                uow,
                self.identity,
                lesson,
                subject,
                {"status": [None, "scheduled"]},
                now=now,
                teacher_ids=[lesson.teacher_id],
            )
            kick_recompute_due_dates(uow, self.kicker, [lesson.id])
            await invalidate_room_pages(uow, self.cache, [lesson.room_id])
            await uow.commit()
        view = await self.reader.lesson_view(lesson.id, locale)
        if view is None:
            raise LessonNotFoundError()
        return (await build_lesson_items([view], self.identity))[0]
