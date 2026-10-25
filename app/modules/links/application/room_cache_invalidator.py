"""Telling others that a lesson's resources changed: room page cache and notebooks."""

from collections.abc import Iterable
from uuid import UUID

from app.modules.links.ports.room_page_cache import RoomPageCache
from app.shared.contracts.academic import LessonRef, ScheduleQueries
from app.shared.tasks import TaskKicker

SYNC_NOTEBOOKS_TASK = "notebooks.sync_lesson_notebooks"


class RoomCacheInvalidator:
    """Forgets `room:{slug}:{date}` and asks the notebooks to re-read the lesson.

    Every place that adds, hides, removes or moderates a lesson resource already calls
    this, so it is also the one place that starts the sync of the students' subject
    and lesson notebooks (NB-AUTO). The notebooks module is reached by task name
    only; links does not import it.
    """

    def __init__(
        self,
        schedule: ScheduleQueries,
        cache: RoomPageCache,
        kicker: TaskKicker | None = None,
    ) -> None:
        """Store the schedule contract, the cache and the task kicker (optional)."""
        self.schedule = schedule
        self.cache = cache
        self.kicker = kicker

    async def lesson(self, lesson: LessonRef) -> None:
        """Clear the room page of this lesson, if it has a room; sync notebooks."""
        if lesson.room_slug is not None:
            await self.cache.invalidate(lesson.room_slug, lesson.date)
        if self.kicker is not None:
            await self.kicker.kick(SYNC_NOTEBOOKS_TASK, lesson_id=str(lesson.id))

    async def lesson_id(self, lesson_id: UUID) -> None:
        """Look the lesson up and clear its room page."""
        lesson = await self.schedule.get_lesson(lesson_id)
        if lesson is not None:
            await self.lesson(lesson)

    async def lesson_ids(self, lesson_ids: Iterable[UUID]) -> None:
        """Clear the room pages of several lessons."""
        for lesson_id in dict.fromkeys(lesson_ids):
            await self.lesson_id(lesson_id)
