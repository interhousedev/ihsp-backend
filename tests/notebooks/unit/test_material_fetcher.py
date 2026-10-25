"""Web materials: downloads are SSRF-safe, typed and capped like URL sources."""

from collections.abc import Callable

from app.modules.notebooks.domain.errors import SourceReadError
from app.modules.notebooks.infrastructure.material_fetcher import HttpMaterialFetcher
from app.modules.notebooks.infrastructure.web_fetcher import HttpWebFetcher
from tests.notebooks.unit.test_web_fetcher import PUBLIC, FakeResolver, page

import httpx
import pytest

PAGE_URL = "https://school.example.org/lesson"
MARKUP = '<article><a href="/notes.pdf">Notes</a></article>'


def _materials(
    handler: Callable[[httpx.Request], httpx.Response],
    table: dict[str, list[str]] | None = None,
) -> tuple[HttpMaterialFetcher, list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    fetcher = HttpWebFetcher(
        resolver=FakeResolver(table, [PUBLIC]),
        transport=httpx.MockTransport(handle),
    )
    return HttpMaterialFetcher(fetcher), sent


async def _failure(materials: HttpMaterialFetcher, url: str, cap: int = 1000) -> str:
    with pytest.raises(SourceReadError) as caught:
        await materials.download(url, cap)
    return caught.value.failure


async def test_the_page_is_scanned_for_candidates() -> None:
    """The markup of the page gives its linked files."""
    materials, _ = _materials(lambda request: page(MARKUP))
    found = await materials.candidates(PAGE_URL, 10)
    assert [c.url for c in found] == ["https://school.example.org/notes.pdf"]


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"]
)
async def test_a_host_resolving_to_a_private_address_is_refused(address: str) -> None:
    """Loopback, private and link-local addresses are never contacted."""
    materials, sent = _materials(
        lambda request: page(b"%PDF", content_type="application/pdf"),
        table={"files.example.org": [address]},
    )
    failure = await _failure(materials, "https://files.example.org/a.pdf")
    assert failure == "forbidden"
    assert sent == []


async def test_a_redirect_to_a_private_address_is_refused() -> None:
    """Every hop is checked again."""
    materials, _ = _materials(
        lambda request: httpx.Response(
            302, headers={"location": "http://127.0.0.1/secret.pdf"}
        )
    )
    assert await _failure(materials, "https://files.example.org/a.pdf") == "forbidden"


async def test_ip_literals_and_other_schemes_are_refused() -> None:
    """Private IP literals and non-http(s) URLs are refused before any request."""
    materials, sent = _materials(lambda request: page(""))
    assert await _failure(materials, "http://10.1.2.3/a.pdf") == "forbidden"
    assert await _failure(materials, "file:///etc/passwd") == "forbidden"
    assert sent == []


async def test_type_and_size_are_checked() -> None:
    """A page is not a material; a file over the cap is too large."""
    html, _ = _materials(lambda request: page("<p>hi</p>"))
    assert await _failure(html, "https://a.example.org/x.pdf") == "unsupported_type"
    big, _ = _materials(lambda request: page(b"x" * 5000, content_type="image/png"))
    assert await _failure(big, "https://a.example.org/x.png", 1000) == "too_large"


async def test_an_accepted_file_comes_back_with_its_type() -> None:
    """The bytes and the content type of the final URL."""
    materials, _ = _materials(
        lambda request: page(b"\x89PNG....", content_type="image/png")
    )
    got = await materials.download("https://a.example.org/x.png", 1000)
    assert (got.content_type, got.data) == ("image/png", b"\x89PNG....")
