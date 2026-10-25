"""DELETE /v1/admin/library/unilibrary/feeds/{id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AdminActor, Library

from fastapi import Response, status


async def delete_unilibrary_feed(
    feed_id: UUID, library: Library, actor: AdminActor
) -> Response:
    """Remove a feed."""
    await library.external.delete_feed.execute(actor, feed_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
