"""GET /r/{room_slug}?date= and POST /r/{room_slug} (the PIN form)."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.public.short_links.web_response import to_response
from app.modules.links.application.render_room_page import SESSION_COOKIE

from fastapi import Depends, Form, Request, Response


async def open_room_page(
    room_slug: str,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
    date: str | None = None,
) -> Response:
    """Show the PIN form or, with a session cookie, the day's lessons (UF-PUB-04).

    A legacy `?pin=` query (printed on a door) is accepted once and answered with a
    redirect to the PIN-free address, so the PIN leaves the address bar at once.
    """
    return await _render(
        container, room_slug, request, ip, pin=request.query_params.get("pin"), day=date
    )


async def submit_room_pin(
    room_slug: str,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
    pin: Annotated[str, Form(max_length=32)] = "",
    date: Annotated[str | None, Form(max_length=10)] = None,
) -> Response:
    """Check the posted PIN; a right one sets the session cookie and redirects."""
    return await _render(container, room_slug, request, ip, pin=pin, day=date)


async def _render(  # noqa: PLR0913
    container: Container,
    room_slug: str,
    request: Request,
    ip: str | None,
    *,
    pin: str | None,
    day: str | None,
) -> Response:
    result = await container.links.render_room_page.execute(
        room_slug,
        pin=pin,
        day=day,
        ip=ip,
        accept_language=request.headers.get("accept-language"),
        session=request.cookies.get(SESSION_COOKIE),
    )
    return to_response(result, secure=container.settings.tokens.refresh_cookie_secure)
