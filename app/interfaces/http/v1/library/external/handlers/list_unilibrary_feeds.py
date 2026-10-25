"""GET /v1/admin/library/unilibrary/feeds."""

from app.interfaces.http.v1.library.deps import AdminActor, Library
from app.interfaces.http.v1.library.external.schemas_external import FeedResponse


async def list_unilibrary_feeds(
    library: Library, actor: AdminActor
) -> list[FeedResponse]:
    """All feeds."""
    feeds = await library.external.list_feeds.execute(actor)
    return [FeedResponse.from_entity(feed) for feed in feeds]
