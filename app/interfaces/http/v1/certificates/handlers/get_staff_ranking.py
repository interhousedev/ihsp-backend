"""GET /v1/certificates/staff/ranking."""

from app.interfaces.http.v1.certificates.deps import (
    ContainerDep,
    FiltersDep,
    StaffActor,
)
from app.interfaces.http.v1.certificates.schemas import StaffRankingResponse

from fastapi import Query


async def get_staff_ranking(
    container: ContainerDep,
    actor: StaffActor,
    filters: FiltersDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> StaffRankingResponse:
    """Return students ranked by their number of certificates."""
    ranked = await container.certificates.get_staff_ranking.execute(
        actor, filters, limit=limit
    )
    return StaffRankingResponse.from_ranked(ranked)
