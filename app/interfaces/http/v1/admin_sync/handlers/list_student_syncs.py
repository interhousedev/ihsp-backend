"""GET /v1/admin/sync/student-syncs: initial student syncs by status."""

from typing import Annotated, Literal

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_sync.schemas import SyncStatusResponse
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def list_student_syncs(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
    status: Annotated[
        Literal["pending", "running", "succeeded", "failed"], Query()
    ] = "failed",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SyncStatusResponse]:
    """Students whose initial sync is in this status, most recently changed first."""
    jobs = await container.academic.marks.list_student_sync_jobs.execute(
        actor, status, limit
    )
    return [SyncStatusResponse.of(job) for job in jobs]
