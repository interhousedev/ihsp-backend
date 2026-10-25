"""POST /v1/admin/broadcasts/audience-count."""

from app.interfaces.http.v1.admin_broadcasts.dependencies import (
    AdminActor,
    ContainerDep,
)
from app.interfaces.http.v1.admin_broadcasts.schemas import (
    AudienceCountBody,
    AudienceCountResponse,
)


async def audience_count(
    body: AudienceCountBody, container: ContainerDep, actor: AdminActor
) -> AudienceCountResponse:
    """Count the active recipients of an audience."""
    count = await container.admin.audience_count.execute(
        actor, body.audience.to_domain()
    )
    return AudienceCountResponse(count=count)
