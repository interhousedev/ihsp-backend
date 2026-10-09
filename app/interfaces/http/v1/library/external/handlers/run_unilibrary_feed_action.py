"""POST /v1/admin/library/unilibrary/feeds/{id}/{action}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AdminActor, Library
from app.interfaces.http.v1.library.external.schemas_external import FeedResponse
from app.modules.library.domain.external_feed import FeedAction


async def run_unilibrary_feed_action(
    feed_id: UUID, action: FeedAction, library: Library, actor: AdminActor
) -> FeedResponse:
    """`enable` and `disable` flip the flag; `dry-run` and `run` answer `409`."""
    feed = await library.external.run_feed_action.execute(actor, feed_id, action)
    return FeedResponse.from_entity(feed)
