"""Search lessons for Administration (ADM-10)."""

from app.modules.academic.application.schedule.common import (
    caller_locale,
)
from app.modules.academic.application.schedule.lesson_items import build_lesson_items
from app.modules.academic.application.schedule.ports.reader import (
    LessonFilters,
    ScheduleReader,
)
from app.modules.academic.application.schedule.results import LessonItemsPage
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory
from app.shared.pagination import decode_cursor, encode_cursor

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class ListLessons:
    """Return a page of lessons ordered by date, period and id."""

    def __init__(self, reader: ScheduleReader, identity: IdentityDirectory) -> None:
        """Store the dependencies."""
        self.reader = reader
        self.identity = identity

    async def execute(
        self,
        actor: Actor,
        filters: LessonFilters,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> LessonItemsPage:
        """Return one page; pass the returned cursor to get the next one."""
        locale = await caller_locale(self.identity, actor)
        page = await self.reader.list_lessons(
            filters,
            cursor=decode_cursor(cursor),
            limit=max(1, min(limit, MAX_LIMIT)),
            locale=locale,
        )
        items = await build_lesson_items(page.items, self.identity)
        next_cursor = encode_cursor(page.next_cursor) if page.next_cursor else None
        return LessonItemsPage(items=items, next_cursor=next_cursor)
