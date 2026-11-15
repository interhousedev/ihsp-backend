"""Sitemaps of the library host: an index, the static pages and the public books."""

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


# Pages of the static app that anyone may open without signing in (`access="public"`).
PUBLIC_APP_PATHS = ("/", "/browse/")
PARTS = ("sitemap-pages.xml", "sitemap-books.xml")


def sitemap_index_xml(base: str) -> str:
    """The sitemap index that points at the parts."""
    parts = "".join(
        f"<sitemap><loc>{escape(f'{base}/{n}')}</loc></sitemap>" for n in PARTS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sitemapindex xmlns="{NAMESPACE}">{parts}</sitemapindex>'
    )


def pages_xml(base: str) -> str:
    """The static public pages, without a date (they change with releases)."""
    urls = "".join(
        f"<url><loc>{escape(base + path)}</loc></url>" for path in PUBLIC_APP_PATHS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="{NAMESPACE}">{urls}</urlset>'
    )


def _xml(body: str) -> Response:
    return Response(
        body,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


async def sitemap(container: Annotated[Container, Depends(get_container)]) -> Response:
    """The sitemap index (submit this one)."""
    base = container.settings.library.public_base_url.rstrip("/")
    return _xml(sitemap_index_xml(base))


async def sitemap_pages(
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """The static public pages."""
    base = container.settings.library.public_base_url.rstrip("/")
    return _xml(pages_xml(base))


async def sitemap_books(
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """The public published books and materials."""
    entries = await container.library.catalogue.list_sitemap.execute()
    return _xml(sitemap_xml(entries))
