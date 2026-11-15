"""Administrator routes: the erasure queue."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.dependencies import get_client_ip
from app.interfaces.http.v1.privacy.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.privacy.schemas import (
    AdminErasureListOut,
    AdminErasureOut,
    ErasureRequestOut,
    ErasureStatusValue,
    RejectIn,
)
from app.modules.privacy.domain.models import ErasureStatus

from fastapi import Depends, Query


async def list_requests(
    container: ContainerDep,
    actor: AdminActor,
    status: ErasureStatusValue | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminErasureListOut:
    """Requests newest first, with the requester's name, login and roles."""
    entries = await container.privacy.list_erasure_requests.execute(
        ErasureStatus(status) if status else None, limit=limit, offset=offset
    )
    return AdminErasureListOut(items=[AdminErasureOut.of_entry(e) for e in entries])


async def approve(
    request_id: UUID,
    container: ContainerDep,
    actor: AdminActor,
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> ErasureRequestOut:
    """Approve: the account is closed and the 30-day window starts."""
    request = await container.privacy.approve_erasure.execute(
        request_id, admin_id=actor.user_id, ip=ip
    )
    return ErasureRequestOut.of(request)


async def reject(
    request_id: UUID,
    body: RejectIn,
    container: ContainerDep,
    actor: AdminActor,
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> ErasureRequestOut:
    """Reject: the account stays; the user is told why."""
    request = await container.privacy.reject_erasure.execute(
        request_id, admin_id=actor.user_id, reason=body.reason, ip=ip
    )
    return ErasureRequestOut.of(request)
