"""GET /v1/certificates/staff/stats."""

from app.interfaces.http.v1.certificates.deps import (
    ContainerDep,
    FiltersDep,
    StaffActor,
)
from app.interfaces.http.v1.certificates.schemas import StaffStatsResponse


async def get_staff_stats(
    container: ContainerDep, actor: StaffActor, filters: FiltersDep
) -> StaffStatsResponse:
    """Return counts by type, level and group."""
    stats = await container.certificates.get_staff_stats.execute(actor, filters)
    return StaffStatsResponse.from_stats(stats)
