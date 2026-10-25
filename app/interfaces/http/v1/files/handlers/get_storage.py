"""GET /v1/me/storage: used space and quota."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.files.schemas import StorageResponse
from app.modules.files.application.storage_usage import StorageUsageView
from app.shared.actor import Actor

from fastapi import Depends


async def get_storage(
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> StorageResponse:
    """Return bytes used, the quota and when this term's files are deleted."""
    usage: StorageUsageView = await container.files.storage_usage.execute(actor)
    return StorageResponse(
        used_bytes=usage.used_bytes,
        quota_bytes=usage.quota_bytes,
        term_id=usage.term_id,
        expires_on=usage.expires_on,
    )
