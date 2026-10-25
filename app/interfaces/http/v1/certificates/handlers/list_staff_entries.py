"""GET /v1/certificates/staff/entries."""

from app.interfaces.http.v1.certificates.deps import (
    ContainerDep,
    FiltersDep,
    StaffActor,
)
from app.interfaces.http.v1.certificates.schemas import StaffEntriesResponse

from fastapi import Query


async def list_staff_entries(
    container: ContainerDep,
    actor: StaffActor,
    filters: FiltersDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> StaffEntriesResponse:
    """Return a page of certificates of the students the caller may see."""
    page = await container.certificates.list_staff_entries.execute(
        actor, filters, limit=limit, offset=offset
    )
    return StaffEntriesResponse.from_page(page)
