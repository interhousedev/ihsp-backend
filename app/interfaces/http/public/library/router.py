"""Routes of the library host's public pages."""

from app.interfaces.http.public.library.handlers import open_item_page, sitemap

from fastapi import APIRouter

router = APIRouter()

router.add_api_route(
    "/b/{slug}", open_item_page.open_item_page, methods=["GET"], include_in_schema=False
)
router.add_api_route(
    "/sitemap.xml", sitemap.sitemap, methods=["GET"], include_in_schema=False
)
router.add_api_route(
    "/sitemap-pages.xml",
    sitemap.sitemap_pages,
    methods=["GET"],
    include_in_schema=False,
)
router.add_api_route(
    "/sitemap-books.xml",
    sitemap.sitemap_books,
    methods=["GET"],
    include_in_schema=False,
)
