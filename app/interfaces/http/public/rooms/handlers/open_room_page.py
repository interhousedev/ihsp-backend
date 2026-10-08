"""GET /r/{room_slug}?pin=&date=."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.public.short_links.web_response import to_response

from fastapi import Depends, Request, Response


async def open_room_page(
    room_slug: str,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
    pin: str | None = None,
    date: str | None = None,
) -> Response:
    """Show the PIN form or the day's lessons of a room (UF-PUB-04)."""
    result = await container.links.render_room_page.execute(
        room_slug,
        pin=pin,
        day=date,
        ip=ip,
        accept_language=request.headers.get("accept-language"),
    )
    return to_response(result)
