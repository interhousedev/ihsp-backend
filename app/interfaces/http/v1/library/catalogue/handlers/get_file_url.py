"""GET /v1/library/items/{id}/files/{fid}/url."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import FileUrlSchema
from app.interfaces.http.v1.library.deps import Library, MaybeSignedIn


async def get_file_url(
    item_id: UUID,
    file_id: UUID,
    library: Library,
    actor: MaybeSignedIn,
    inline: bool = False,
) -> FileUrlSchema:
    """A URL valid for 15 minutes; `inline=1` is for the reader, else a download."""
    view = await library.catalogue.get_file_url.execute(
        actor, item_id, file_id, inline=inline
    )
    return FileUrlSchema.from_view(view)
