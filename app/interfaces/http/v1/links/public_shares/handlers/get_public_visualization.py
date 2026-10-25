"""GET /v1/public/visualizations/{slug}."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.v1.links.public_shares.schemas import PublicVisualization

from fastapi import Depends


async def get_public_visualization(
    slug: str,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> PublicVisualization:
    """Return a shared bot answer: 404 unknown or revoked, 410 expired."""
    view = await container.links.get_public_message.execute(slug, ip=ip)
    return PublicVisualization(
        text=view.text, created_at=view.created_at, expires_at=view.expires_at
    )
