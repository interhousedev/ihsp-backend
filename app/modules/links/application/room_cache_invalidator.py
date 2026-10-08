"""Clearing the cached room page when a lesson's resources change (ROOM-8)."""

from collections.abc import Iterable
from uuid import UUID

from app.modules.links.ports.room_page_cache import RoomPageCache
from app.shared.contracts.academic import LessonRef, ScheduleQueries


class RoomCacheInvalidator:
    """Forgets `room:{slug}:{date}` for lessons held in a room."""

    def __init__(self, schedule: ScheduleQueries, cache: RoomPageCache) -> None:
        """Store the schedule contract and the cache."""
        self.schedule = schedule
        self.cache = cache

    async def lesson(self, lesson: LessonRef) -> None:
        """Clear the room page of this lesson, if it has a room."""
        if lesson.room_slug is not None:
            await self.cache.invalidate(lesson.room_slug, lesson.date)

    async def lesson_id(self, lesson_id: UUID) -> None:
        """Look the lesson up and clear its room page."""
        lesson = await self.schedule.get_lesson(lesson_id)
        if lesson is not None:
            await self.lesson(lesson)

    async def lesson_ids(self, lesson_ids: Iterable[UUID]) -> None:
        """Clear the room pages of several lessons."""
        for lesson_id in dict.fromkeys(lesson_ids):
            await self.lesson_id(lesson_id)
