"""POST /v1/library/items/{id}/report."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.materials.schemas_materials import (
    LibraryReportBody,
)

from fastapi import Response, status


async def report_item(
    item_id: UUID, body: LibraryReportBody, library: Library, actor: SignedIn
) -> Response:
    """Report an item to the librarians; the owner never learns who did."""
    await library.materials.report_item.execute(actor, item_id, body.reason, body.text)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
