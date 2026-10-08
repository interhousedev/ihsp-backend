"""robots.txt of the public hosts: nothing is indexed."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

ROBOTS_TXT = "User-agent: *\nDisallow: /\n"


async def robots() -> PlainTextResponse:
    """Disallow crawling of short links, shares and room pages (ROOM-5)."""
    return PlainTextResponse(ROBOTS_TXT)


router = APIRouter()
router.add_api_route("/robots.txt", robots, methods=["GET"], include_in_schema=False)
