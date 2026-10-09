"""Change a single lesson by hand; regeneration leaves it alone (UF-ADM-07)."""

import datetime as dt
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
    raise_on_lesson_conflicts,
    slot_times,
)
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.room_cache import (
    invalidate_room_pages,
)
from app.modules.academic.application.schedule.unset import UNSET, Unset
from app.modules.academic.domain.schedule.conflicts import LessonSlot
from app.modules.academic.domain.schedule.errors import (
    EntryInvalidError,
    LessonNotFoundError,
    SubjectNotFoundError,
)
from app.modules.academic.domain.schedule.lesson import Lesson, LessonStatus
from app.modules.academic.domain.schedule.lesson_changes import (
    merge_changes,
    time_label,
)
from app.modules.academic.domain.schedule.subject import subject_name
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.tasks import TaskKicker

_STATUSES: dict[str, LessonStatus] = {
    "scheduled": "scheduled",
    "cancelled": "cancelled",
}


def _status(value: str) -> LessonStatus:
    if value not in _STATUSES:
        raise EntryInvalidError(params={"reason": "status"})
    return _STATUSES[value]


@dataclass(frozen=True, slots=True)
class LessonPatch:
    """A partial change; UNSET means "keep", None clears nullable fields."""

    status: str | None = None
    teacher_id: UUID | None | Unset = UNSET
    subject_id: UUID | None = None
    room_name: str | None | Unset = UNSET
    date: dt.date | None = None
    period: int | None = None
    topic: str | None | Unset = UNSET


@dataclass(frozen=True, slots=True)
class _Before:
    subject_id: UUID
    teacher_id: UUID | None
    room_id: UUID | None
    starts_at: dt.datetime
    ends_at: dt.datetime
    date: dt.date
    status: str


class UpdateLesson:
    """Cancel, move or reassign one lesson and tell the people affected."""

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

    async def execute(
        self, actor: Actor, lesson_id: UUID, patch: LessonPatch
    ) -> dict[str, Any]:
        """Apply the patch and return the LessonItem."""
        locale = await caller_locale(self.identity, actor)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            lesson = await uow.lessons.get(lesson_id)
            if lesson is None:
                raise LessonNotFoundError()
            before = _Before(
                lesson.subject_id,
                lesson.teacher_id,
                lesson.room_id,
                lesson.starts_at,
                lesson.ends_at,
                lesson.date,
                lesson.status,
            )
            await self._apply(uow, lesson, patch, now)
            changes = await self._diff(uow, before, lesson, locale)
            if changes:
                await self._record(uow, lesson, before, changes, now)
            await uow.lessons.save(lesson)
            await uow.commit()
        view = await self.reader.lesson_view(lesson.id, locale)
        if view is None:
            raise LessonNotFoundError()
        return (await build_lesson_items([view], self.identity))[0]

    async def _apply(
        self,
        uow: ScheduleUnitOfWork,
        lesson: Lesson,
        patch: LessonPatch,
        now: dt.datetime,
    ) -> None:
        if patch.status is not None:
            lesson.status = _status(patch.status)
        if patch.subject_id is not None:
            await self._set_subject(uow, lesson, patch.subject_id)
        if not isinstance(patch.teacher_id, Unset):
            lesson.teacher_id = patch.teacher_id
        if not isinstance(patch.room_name, Unset):
            lesson.room_id = await self._room_id(uow, patch.room_name, now)
        if not isinstance(patch.topic, Unset):
            lesson.topic = (patch.topic or "").strip() or None
        await self._move(uow, lesson, patch)

    @staticmethod
    async def _set_subject(
        uow: ScheduleUnitOfWork, lesson: Lesson, subject_id: UUID
    ) -> None:
        if await uow.subjects.get(subject_id) is None:
            raise SubjectNotFoundError()
        lesson.subject_id = subject_id

    @staticmethod
    async def _room_id(
        uow: ScheduleUnitOfWork, name: str | None, now: dt.datetime
    ) -> UUID | None:
        if name is None or not name.strip():
            return None
        return (await ensure_room_in(uow, name, now)).id

    @staticmethod
    async def _move(
        uow: ScheduleUnitOfWork, lesson: Lesson, patch: LessonPatch
    ) -> None:
        if patch.date is None and patch.period is None:
            return
        day = patch.date or lesson.date
        period = patch.period or lesson.period
        if day == lesson.date and period == lesson.period:
            return
        term, starts_at, ends_at = await slot_times(uow, day, period)
        await uow.lock_term(term.id)
        lesson.term_id = term.id
        lesson.date, lesson.period = day, period
        lesson.starts_at, lesson.ends_at = starts_at, ends_at

    async def _diff(
        self, uow: ScheduleUnitOfWork, before: _Before, lesson: Lesson, locale: str
    ) -> dict[str, list[Any]]:
        """Describe what changed among room, teacher, subject, time, date, status."""
        changes: dict[str, list[Any]] = {}
        if before.status != lesson.status:
            changes["status"] = [before.status, lesson.status]
        if before.date != lesson.date:
            changes["date"] = [before.date.isoformat(), lesson.date.isoformat()]
        if (before.starts_at, before.ends_at) != (lesson.starts_at, lesson.ends_at):
            changes["time"] = [
                time_label(before.starts_at, before.ends_at),
                time_label(lesson.starts_at, lesson.ends_at),
            ]
        if before.room_id != lesson.room_id:
            changes["room"] = [
                await self._room_name(uow, before.room_id),
                await self._room_name(uow, lesson.room_id),
            ]
        if before.teacher_id != lesson.teacher_id:
            changes["teacher"] = [
                await self._teacher_name(before.teacher_id),
                await self._teacher_name(lesson.teacher_id),
            ]
        if before.subject_id != lesson.subject_id:
            changes["subject"] = [
                await self._subject_name(uow, before.subject_id, locale),
                await self._subject_name(uow, lesson.subject_id, locale),
            ]
        return changes

    @staticmethod
    async def _room_name(uow: ScheduleUnitOfWork, room_id: UUID | None) -> str | None:
        room = await uow.rooms.get(room_id) if room_id else None
        return room.name if room else None

    async def _teacher_name(self, teacher_id: UUID | None) -> str | None:
        user = await self.identity.get_user(teacher_id) if teacher_id else None
        return f"{user.last_name} {user.first_name}" if user else None

    @staticmethod
    async def _subject_name(
        uow: ScheduleUnitOfWork, subject_id: UUID, locale: str
    ) -> str | None:
        subject = await uow.subjects.get(subject_id)
        return subject_name(subject, locale) if subject else None

    async def _record(
        self,
        uow: ScheduleUnitOfWork,
        lesson: Lesson,
        before: _Before,
        changes: dict[str, list[Any]],
        now: dt.datetime,
    ) -> None:
        lesson.is_overridden = True
        lesson.emis_class_id = None  # edited by hand: EMIS no longer manages it
        lesson.changes = merge_changes(lesson.changes, changes)
        if lesson.status == "scheduled":
            await raise_on_lesson_conflicts(
                uow,
                LessonSlot(
                    lesson.id,
                    lesson.starts_at,
                    lesson.ends_at,
                    lesson.teacher_id,
                    lesson.room_id,
                    lesson.audience,
                ),
            )
        subject = await uow.subjects.get(lesson.subject_id)
        if subject is None:
            raise SubjectNotFoundError()
        await notify_lesson_changed(
            uow,
            self.identity,
            lesson,
            subject,
            changes,
            now=now,
            teacher_ids=[before.teacher_id, lesson.teacher_id],
        )
        kick_recompute_due_dates(uow, self.kicker, [lesson.id])
        await invalidate_room_pages(uow, self.cache, [before.room_id, lesson.room_id])
