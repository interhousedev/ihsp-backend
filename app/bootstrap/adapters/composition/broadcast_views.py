"""BroadcastViews over the admin module's `ListBroadcasts`."""

import datetime as dt

from app.interfaces.http.v1.admin_broadcasts.schemas import BroadcastResponse
from app.interfaces.http.v1.composition.ports import JsonObject
from app.modules.admin.application.broadcast_view import BroadcastView
from app.modules.admin.application.list_broadcasts import ListBroadcasts
from app.modules.admin.domain.broadcast import BroadcastStatus
from app.shared.actor import Actor

PAGE_SIZE = 100
# Scheduled broadcasts are a handful; this many pages is a safety stop.
MAX_PAGES = 20
NEVER = dt.datetime.max.replace(tzinfo=dt.UTC)


class BroadcastViewsAdapter:
    """Composition <- admin: broadcasts for the dashboard."""

    def __init__(self, list_broadcasts: ListBroadcasts) -> None:
        """Keep the broadcast list use case."""
        self._list_broadcasts = list_broadcasts

    async def scheduled(self, actor: Actor, limit: int) -> list[JsonObject]:
        """Return `BroadcastItem` dicts with status `scheduled`, soonest first.

        The use case lists newest-created first, so every page is read before the
        soonest ones are chosen.
        """
        views: list[BroadcastView] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            page = await self._list_broadcasts.execute(
                actor, status=BroadcastStatus.SCHEDULED, cursor=cursor, limit=PAGE_SIZE
            )
            views.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        views.sort(key=lambda view: view.broadcast.scheduled_at or NEVER)
        return [
            BroadcastResponse.from_view(view).model_dump(mode="json")
            for view in views[:limit]
        ]
