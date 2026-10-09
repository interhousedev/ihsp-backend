"""robots.txt of the public hosts: nothing is indexed, except the library's pages."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.public.library.robots import (
    is_library_host,
    library_robots_txt,
)

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

ROBOTS_TXT = "User-agent: *\nDisallow: /\n"


async def robots(
    request: Request, container: Annotated[Container, Depends(get_container)]
) -> PlainTextResponse:
    """Disallow crawling (ROOM-5); the library host shows its public pages."""
    settings = container.settings.library
    if is_library_host(request, settings):
        return PlainTextResponse(library_robots_txt(settings))
    return PlainTextResponse(ROBOTS_TXT)


router = APIRouter()
router.add_api_route("/robots.txt", robots, methods=["GET"], include_in_schema=False)
