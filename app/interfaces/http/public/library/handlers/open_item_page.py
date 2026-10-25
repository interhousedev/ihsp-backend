"""GET /b/{slug}: the server-rendered page of a book or material."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.public.library.json_ld import json_ld
from app.interfaces.http.public.library.renderer import render
from app.modules.library.application.catalogue.public_pages import PublicItemPage
from app.modules.library.application.locale import resolve_locale
from app.modules.library.domain.enums import ItemKind

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

DESCRIPTION_CHARS = 200
BASE_HEADERS = {"Referrer-Policy": "strict-origin-when-cross-origin"}


async def open_item_page(
    slug: str, request: Request, container: Annotated[Container, Depends(get_container)]
) -> HTMLResponse:
    """The page for people and link previews; unknown or hidden items get a 404 page."""
    library = container.library
    accept_language = request.headers.get("accept-language")
    page = await library.catalogue.get_public_item_page.execute(
        slug, accept_language=accept_language
    )
    if page is None:
        locale = await resolve_locale(library.core.identity, None, accept_language)
        html = render("not_found", locale, container.i18n, _not_found(container))
        return HTMLResponse(html, status_code=404, headers=_headers(indexable=False))
    html = render("item", page.locale, container.i18n, _context(page))
    return HTMLResponse(
        html,
        headers={
            **_headers(indexable=page.indexable),
            "Cache-Control": "public, max-age=300",
        },
    )


def _not_found(container: Container) -> dict[str, object]:
    return {"home_url": container.settings.library.public_base_url}


def _headers(*, indexable: bool) -> dict[str, str]:
    headers = dict(BASE_HEADERS)
    if not indexable:
        headers["X-Robots-Tag"] = "noindex"
        headers["Cache-Control"] = "no-store"
    return headers


def _context(page: PublicItemPage) -> dict[str, object]:
    text = " ".join((page.description or "").split())
    short = (
        text
        if len(text) <= DESCRIPTION_CHARS
        else text[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
    )
    return {
        "page": page,
        "short_description": short,
        "og_type": "book" if page.kind is ItemKind.BOOK else "article",
        "json_ld": json_ld(page),
    }
