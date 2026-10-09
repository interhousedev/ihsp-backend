"""PATCH /v1/admin/library/unilibrary/feeds/{id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AdminActor, Library
from app.interfaces.http.v1.library.external.schemas_external import (
    FeedPatchBody,
    FeedResponse,
)


async def update_unilibrary_feed(
    feed_id: UUID, body: FeedPatchBody, library: Library, actor: AdminActor
) -> FeedResponse:
    """Change the keys that were sent."""
    feed = await library.external.update_feed.execute(
        actor,
        feed_id,
        name=body.name,
        params=body.params,
        max_items=body.max_items,
    )
    return FeedResponse.from_entity(feed)
