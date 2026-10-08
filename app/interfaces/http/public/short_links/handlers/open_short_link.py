"""GET /s/{slug} (dev) and GET /{slug} on the short link host."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.public.short_links.web_response import to_response

from fastapi import Depends, Request, Response


async def open_short_link(
    slug: str,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> Response:
    """Redirect, show the interstitial, or answer 404/410 (UF-PUB-03)."""
    result = await container.links.open_short_link.execute(
        slug, ip=ip, accept_language=request.headers.get("accept-language")
    )
    return to_response(result)
