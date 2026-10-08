"""GET /v1/public/shares/{slug}."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.v1.links.public_shares.schemas import (
    PublicShare,
    public_share,
)

from fastapi import Depends


async def get_public_share(
    slug: str,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> PublicShare:
    """Return a shared chat or flash card set without login (SHR-2, UF-PUB-01)."""
    view = await container.links.get_public_share.execute(slug, ip=ip)
    return public_share(view)
