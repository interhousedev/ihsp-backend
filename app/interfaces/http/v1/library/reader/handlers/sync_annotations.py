"""POST /v1/me/library/annotations/sync."""

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_reader import (
    AnnotationResponse,
    AnnotationsSyncBody,
    AnnotationsSyncResponse,
)


async def sync_annotations(
    body: AnnotationsSyncBody, library: Library, actor: SignedIn
) -> AnnotationsSyncResponse:
    """Apply a device's queued changes (at most 200) and answer with their state."""
    items = await library.reader.sync_annotations.execute(
        actor, upserts=[u.to_data() for u in body.upserts], deletes=body.deletes
    )
    return AnnotationsSyncResponse(
        items=[AnnotationResponse.from_entity(a) for a in items]
    )
