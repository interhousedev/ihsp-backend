"""List reported links for Administration (ADM-13, UF-ADM-10)."""

from app.modules.links.application.cursors import (
    decode_moderation_cursor,
    encode_moderation_cursor,
)
from app.modules.links.application.moderation_views import ModerationViews
from app.modules.links.application.views import ModerationPage
from app.modules.links.ports.link_repository import ModerationCursor
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role

MAX_LIMIT = 100


class ListModerationQueue:
    """Reported links not reviewed since their last report, most reported first."""

    def __init__(self, *, uow_factory: UowFactory, views: ModerationViews) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(
        self, actor: Actor, *, cursor: str | None = None, limit: int = 20
    ) -> ModerationPage:
        """Return one page of the queue."""
        actor.require(Role.ADMIN)
        size = max(1, min(limit, MAX_LIMIT))
        after = decode_moderation_cursor(cursor)
        async with self.uow_factory() as uow:
            rows = await uow.links.moderation_queue(after=after, limit=size + 1)
        page = rows[:size]
        next_cursor = None
        if len(rows) > size and page:
            tail = page[-1]
            assert tail.last_reported_at is not None
            next_cursor = encode_moderation_cursor(
                ModerationCursor(tail.reports, tail.last_reported_at, tail.id)
            )
        return ModerationPage(
            items=await self.views.build(page), next_cursor=next_cursor
        )
