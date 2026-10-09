"""DELETE /v1/library/materials/{id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn

from fastapi import Response, status


async def withdraw_material(
    item_id: UUID, library: Library, actor: SignedIn
) -> Response:
    """The owner takes the material back (a draft is deleted)."""
    await library.materials.withdraw_material.execute(actor, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
