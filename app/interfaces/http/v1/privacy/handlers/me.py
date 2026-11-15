"""Signed-in routes: data exports and the erasure request."""

from uuid import UUID

from app.interfaces.http.v1.privacy.deps import ContainerDep, UserActor
from app.interfaces.http.v1.privacy.schemas import (
    ErasureRequestOut,
    ExportDownloadOut,
    ExportListOut,
    ExportOut,
    MyErasureOut,
)


async def request_export(container: ContainerDep, actor: UserActor) -> ExportOut:
    """Queue an export of the caller's data (one per 24 hours)."""
    job = await container.privacy.request_export.execute(actor.user_id)
    return ExportOut.of(job)


async def list_exports(container: ContainerDep, actor: UserActor) -> ExportListOut:
    """The caller's recent exports."""
    jobs = await container.privacy.list_exports.execute(actor.user_id)
    return ExportListOut(items=[ExportOut.of(j) for j in jobs])


async def download_export(
    export_id: UUID, container: ContainerDep, actor: UserActor
) -> ExportDownloadOut:
    """A 60-second link to the archive; 404 unless it is the caller's own, ready."""
    url = await container.privacy.download_export.execute(actor.user_id, export_id)
    return ExportDownloadOut(url=url)


async def get_erasure(container: ContainerDep, actor: UserActor) -> MyErasureOut:
    """The caller's open erasure request."""
    request = await container.privacy.get_my_erasure.execute(actor.user_id)
    return MyErasureOut(request=ErasureRequestOut.of(request) if request else None)


async def cancel_erasure(
    container: ContainerDep, actor: UserActor
) -> ErasureRequestOut:
    """Withdraw a request that is still waiting for review."""
    request = await container.privacy.cancel_erasure.execute(actor.user_id)
    return ErasureRequestOut.of(request)
