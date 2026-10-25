"""GET /sitemap.xml: the public published books and materials."""

from typing import Annotated

# escape() only encodes output text; nothing is parsed, so defusedxml is not needed.
from xml.sax.saxutils import escape  # nosec B406

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.modules.library.application.catalogue.public_pages import SitemapEntry

from fastapi import Depends, Response

NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


def sitemap_xml(entries: list[SitemapEntry]) -> str:
    """The sitemap document for the entries."""
    urls = "".join(
        f"<url><loc>{escape(entry.url)}</loc>"
        f"<lastmod>{entry.changed.date().isoformat()}</lastmod></url>"
        for entry in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="{NAMESPACE}">{urls}</urlset>'
    )


async def sitemap(container: Annotated[Container, Depends(get_container)]) -> Response:
    """List the URLs search engines may index."""
    entries = await container.library.catalogue.list_sitemap.execute()
    return Response(
        sitemap_xml(entries),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )
