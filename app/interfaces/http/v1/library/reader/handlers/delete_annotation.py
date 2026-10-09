"""DELETE /v1/me/library/annotations/{annotation_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn


async def delete_annotation(
    annotation_id: UUID, library: Library, actor: SignedIn
) -> None:
    """Delete an annotation of the caller."""
    await library.reader.delete_annotation.execute(actor, annotation_id)
