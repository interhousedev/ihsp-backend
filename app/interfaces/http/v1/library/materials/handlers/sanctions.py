"""GET and POST /v1/admin/library/sanctions."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AdminActor, Library
from app.interfaces.http.v1.library.materials.schemas_moderation import (
    SanctionBody,
    SanctionResponse,
)


async def list_sanctions(
    library: Library, actor: AdminActor, user_id: UUID | None = None
) -> list[SanctionResponse]:
    """Warnings and bans, newest first; of one user with `?user_id=`."""
    sanctions = await library.materials.list_sanctions.execute(actor, user_id=user_id)
    return [SanctionResponse.from_entity(s) for s in sanctions]


async def create_sanction(
    body: SanctionBody, library: Library, actor: AdminActor
) -> SanctionResponse:
    """Warn a user or ban them from uploading."""
    sanction = await library.materials.create_sanction.execute(
        actor,
        user_id=body.user_id,
        kind=body.kind,
        until=body.until,
        reason=body.reason,
    )
    return SanctionResponse.from_entity(sanction)
