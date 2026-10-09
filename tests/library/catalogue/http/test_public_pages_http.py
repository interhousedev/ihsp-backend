"""LIB-14: `/b/{slug}`, `/sitemap.xml` and the library robots.txt."""

import json
import re
from collections.abc import Awaitable, Callable

from app.interfaces.http.public.library import ROUTERS
from app.interfaces.http.public.library.robots import (
    is_library_host,
    library_robots_txt,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus, Rights, Visibility
from app.modules.library.wiring import LibraryServices
from app.settings import LibrarySettings
from tests.factories.library import make_book, make_external, make_material
from tests.library.catalogue.helpers import put

import pytest
from fastapi import Request
from httpx import AsyncClient

Api = Callable[..., Awaitable[AsyncClient]]
StoreItem = Callable[[Item], Awaitable[Item]]


def _public_book(**fields: object) -> Item:
    book = make_book(
        title="O'tkan kunlar",
        visibility=Visibility.PUBLIC,
        rights=Rights.PUBLIC_DOMAIN,
        authors=["Abdulla Qodiriy"],
        author_label="Abdulla Qodiriy",
        description="The first great Uzbek novel.",
        year_published=1925,
    )
    for key, value in fields.items():
        setattr(book, key, value)
    assert book.book is not None
    book.book.rights_basis = {"author_death_year": 1938, "attribution": "A. Q."}
    return book


async def test_public_book_page_has_open_graph_json_ld_and_a_read_link(
    api: Api, library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-14: server-rendered HTML for people and link previews."""
    book = await put(library.core.uow_factory, store_item, _public_book())
    client = await api(None)

    response = await client.get(f"/b/{book.slug}", headers={"accept-language": "en"})

    html = response.text
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>O&#39;tkan kunlar</h1>" in html
    assert 'property="og:title" content="O&#39;tkan kunlar"' in html
    assert f'rel="canonical" href="https://library.ihsu.uz/b/{book.slug}"' in html
    assert "noindex" not in html and "x-robots-tag" not in response.headers
    assert f'href="https://library.ihsu.uz/item/?id={book.slug}"' in html
    assert "Read in the library" in html and "Abdulla Qodiriy" in html
    assert "public domain" in html
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert block is not None
    ld = json.loads(block[1])
    assert ld["@type"] == "Book" and ld["name"] == "O'tkan kunlar"
    assert ld["author"] == [{"@type": "Person", "name": "Abdulla Qodiriy"}]
    assert ld["isAccessibleForFree"] is True and ld["datePublished"] == "1925"


async def test_lyceum_item_page_asks_to_sign_in_and_is_not_indexed(
    api: Api, library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-14: title and cover are not secret; the file link is not shown."""
    book = await put(library.core.uow_factory, store_item, make_book(title="Fizika 10"))
    client = await api(None)

    response = await client.get(f"/b/{book.slug}", headers={"accept-language": "en"})

    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex"
    assert '<meta name="robots" content="noindex, nofollow">' in response.text
    assert "Sign in to read" in response.text
    assert "Read in the library" not in response.text
    assert 'isAccessibleForFree": false' in response.text


async def test_page_language_follows_the_browser(
    api: Api, library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-14: Russian and Uzbek visitors get their own labels."""
    book = await put(library.core.uow_factory, store_item, _public_book())
    client = await api(None)

    russian = await client.get(f"/b/{book.slug}", headers={"accept-language": "ru"})
    uzbek = await client.get(f"/b/{book.slug}", headers={"accept-language": "uz"})

    assert "Читать в библиотеке" in russian.text and 'lang="ru"' in russian.text
    assert "Kutubxonada o‘qish" in uzbek.text


async def test_unknown_held_unpublished_and_hidden_items_look_the_same(
    api: Api, library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-14: one 404 page; it never reveals why."""
    uow_factory = library.core.uow_factory
    held = await put(uow_factory, store_item, make_material(status=ItemStatus.HELD))
    gone = await put(uow_factory, store_item, make_book(status=ItemStatus.UNPUBLISHED))
    hidden = await put(uow_factory, store_item, make_book(visibility=Visibility.HIDDEN))
    draft = await put(uow_factory, store_item, make_book(status=ItemStatus.DRAFT))
    client = await api(None)

    pages = [
        await client.get(f"/b/{slug}")
        for slug in (held.slug, gone.slug, hidden.slug, draft.slug, "no-such-slug")
    ]

    assert {p.status_code for p in pages} == {404}
    assert len({p.text for p in pages}) == 1
    assert all(p.headers["x-robots-tag"] == "noindex" for p in pages)
    assert all(p.headers["cache-control"] == "no-store" for p in pages)


async def test_text_of_an_item_is_escaped(
    api: Api, library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-14: no markup from titles or descriptions reaches the page."""
    book = await put(
        library.core.uow_factory,
        store_item,
        _public_book(
            title="<script>alert(1)</script>",
            description="</script><img src=x onerror=alert(2)>",
        ),
    )
    client = await api(None)

    html = (await client.get(f"/b/{book.slug}")).text

    assert "<script>alert(1)" not in html
    assert "<img src=x" not in html
    assert html.count("</script>") == 1  # only the one closing the JSON-LD block


async def test_external_card_page_links_out_when_visitors_may_see_cards(
    api: Api,
    library: LibraryServices,
    store_item: StoreItem,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LIB-12, LIB-14: UniLibrary pages show the link-out, never a reader."""
    record = make_external(title="Elektronika")
    record.visibility = Visibility.PUBLIC
    await put(library.core.uow_factory, store_item, record)
    client = await api(None)

    closed = await client.get(f"/b/{record.slug}")
    monkeypatch.setattr(library.core.settings, "unilibrary_enabled", True)
    monkeypatch.setattr(library.core.settings, "unilibrary_anonymous_cards", True)
    opened = await client.get(f"/b/{record.slug}", headers={"accept-language": "en"})

    assert closed.status_code == 404
    assert opened.status_code == 200
    assert 'href="https://unilibrary.uz/literature/355186"' in opened.text
    assert 'rel="noopener noreferrer"' in opened.text
    assert "Read in the library" not in opened.text


async def test_sitemap_lists_public_pages_only(
    api: Api, library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-14: lyceum-only and removed items are not in the sitemap."""
    open_book = await put(library.core.uow_factory, store_item, _public_book())
    await put(library.core.uow_factory, store_item, make_book(title="Yopiq"))
    client = await api(None)

    response = await client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.text.count("<url>") == 1
    assert f"<loc>https://library.ihsu.uz/b/{open_book.slug}</loc>" in response.text
    assert "<lastmod>2026-10-06</lastmod>" in response.text


def test_library_robots_txt_allows_pages_and_points_at_the_sitemap() -> None:
    """LIB-14: crawlers may read `/b/` and the sitemap, not the app's own paths."""
    text = library_robots_txt(
        LibrarySettings(public_base_url="https://library.ihsu.uz/")
    )

    assert "Allow: /b/" in text and "Allow: /sitemap.xml" in text
    assert "Disallow: /manage/" in text
    assert text.endswith("Sitemap: https://library.ihsu.uz/sitemap.xml\n")


def _request(host: str, forwarded: str | None = None) -> Request:
    headers = [(b"host", host.encode())]
    if forwarded:
        headers.append((b"x-forwarded-host", forwarded.encode()))
    return Request({"type": "http", "headers": headers})


def test_library_host_is_recognised_behind_a_proxy() -> None:
    """LIB-14: `Host` or `X-Forwarded-Host`, with or without a port."""
    settings = LibrarySettings(public_base_url="https://library.ihsu.uz")

    assert is_library_host(_request("library.ihsu.uz"), settings)
    assert is_library_host(_request("LIBRARY.ihsu.uz:443"), settings)
    assert is_library_host(_request("api:8000", forwarded="library.ihsu.uz"), settings)
    assert not is_library_host(_request("ihsu.uz"), settings)
    assert not is_library_host(_request("sp.ihsu.uz"), settings)


def test_public_package_exports_its_routers() -> None:
    """LIB-14: the package is mounted (`ROUTERS` is not empty)."""
    assert len(ROUTERS) == 1
