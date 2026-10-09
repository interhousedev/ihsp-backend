"""POST /v1/admin/library/unilibrary/feeds."""

from app.interfaces.http.v1.library.deps import AdminActor, Library
from app.interfaces.http.v1.library.external.schemas_external import (
    FeedInputBody,
    FeedResponse,
)


async def create_unilibrary_feed(
    body: FeedInputBody, library: Library, actor: AdminActor
) -> FeedResponse:
    """Store a new feed (disabled; no sync runs it yet)."""
    feed = await library.external.create_feed.execute(
        actor, name=body.name, params=body.params, max_items=body.max_items
    )
    return FeedResponse.from_entity(feed)
