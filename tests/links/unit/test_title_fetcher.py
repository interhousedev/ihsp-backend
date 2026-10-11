"""SL-8, UF-WEB-07 2e: reading page titles safely."""

from app.modules.links.infrastructure.title_fetcher import (
    HttpTitleFetcher,
    parse_title,
)

import httpx
import pytest

PUBLIC = "93.184.216.34"


async def _resolver(host: str) -> list[str]:
    table = {"internal.test": ["10.0.0.5"], "loopback.test": ["127.0.0.1"]}
    return table.get(host, [PUBLIC])


def _fetcher(handler: httpx.MockTransport) -> HttpTitleFetcher:
    return HttpTitleFetcher(resolver=_resolver, transport=handler)


def _html(body: str, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(
        status,
        content=body.encode(),
        headers={"content-type": "text/html; charset=utf-8", **headers},
    )


@pytest.mark.parametrize(
    ("markup", "title"),
    [
        ("<html><head><title>Hello</title></head></html>", "Hello"),
        ("<title>\n  Two\n   words \n</title><title>Second</title>", "Two words"),
        ("<TITLE>Caps</TITLE>", "Caps"),
        ("<title>Tom &amp; Jerry</title>", "Tom & Jerry"),
        ("<p>No title</p>", None),
        ("<title></title>", None),
        ("<title>" + "x" * 500 + "</title>", "x" * 200),
    ],
)
def test_title_parser(markup: str, title: str | None) -> None:
    """The first <title>, whitespace collapsed, at most 200 characters."""
    assert parse_title(markup) == title


async def test_the_title_of_a_page_is_returned() -> None:
    """UF-WEB-07 step 2: the page <title> names the link."""
    transport = httpx.MockTransport(lambda r: _html("<title>Khan: Derivatives</title>"))

    title = await _fetcher(transport).fetch_title("https://example.org/d")

    assert title == "Khan: Derivatives"


async def test_up_to_three_redirects_are_followed() -> None:
    """Redirects are followed manually, at most three."""

    def handler(request: httpx.Request) -> httpx.Response:
        step = int(request.url.path.strip("/") or 0)
        if step < 3:
            return httpx.Response(302, headers={"location": f"/{step + 1}"})
        return _html("<title>Final</title>")

    assert (
        await _fetcher(httpx.MockTransport(handler)).fetch_title("https://example.org/")
        == "Final"
    )


async def test_a_fourth_redirect_falls_back_to_the_host_name() -> None:
    """UF-WEB-07 2e: when the title cannot be read the domain is used."""
    transport = httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"location": "/again"})
    )

    assert (
        await _fetcher(transport).fetch_title("https://example.org/") == "example.org"
    )


@pytest.mark.parametrize("host", ["internal.test", "loopback.test"])
async def test_internal_hosts_are_never_contacted(host: str) -> None:
    """SSRF: private and loopback addresses are refused before any request."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _html("<title>Secret</title>")

    title = await _fetcher(httpx.MockTransport(handler)).fetch_title(
        f"http://{host}/admin"
    )

    assert title == host
    assert calls == []


async def test_a_redirect_to_an_internal_host_is_refused() -> None:
    """SSRF: every redirect target is checked again."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["host"])
        if request.headers["host"] == "example.org":
            return httpx.Response(302, headers={"location": "http://internal.test/x"})
        return _html("<title>Secret</title>")

    title = await _fetcher(httpx.MockTransport(handler)).fetch_title(
        "https://example.org/"
    )

    assert title == "example.org"
    assert calls == ["example.org"]


async def test_the_request_goes_to_the_validated_address_with_the_real_host() -> None:
    """SL-8 (DNS rebinding): connect to the checked IP; the name is in Host and SNI."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _html("<title>Pinned</title>")

    title = await _fetcher(httpx.MockTransport(handler)).fetch_title(
        "https://example.org:8443/page?q=1"
    )

    assert title == "Pinned"
    [request] = seen
    assert request.url.host == PUBLIC
    assert request.url.port == 8443
    assert request.url.raw_path == b"/page?q=1"
    assert request.headers["host"] == "example.org:8443"
    assert request.extensions["sni_hostname"] == "example.org"


async def test_a_name_that_resolves_to_a_mapped_private_address_is_refused() -> None:
    """SL-8: IPv4-mapped IPv6 answers are no way around the address check."""
    calls: list[str] = []

    async def resolver(host: str) -> list[str]:
        return [PUBLIC, "::ffff:10.0.0.5"]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _html("<title>Secret</title>")

    fetcher = HttpTitleFetcher(
        resolver=resolver, transport=httpx.MockTransport(handler)
    )

    assert await fetcher.fetch_title("http://example.org/") == "example.org"
    assert calls == []


async def test_a_connection_to_an_unexpected_peer_is_dropped() -> None:
    """SL-8: the socket must be connected to the validated address."""

    class _Stream:
        def get_extra_info(self, name: str) -> object:
            return ("10.0.0.5", 80) if name == "server_addr" else None

    def handler(request: httpx.Request) -> httpx.Response:
        response = _html("<title>Secret</title>")
        response.extensions["network_stream"] = _Stream()
        return response

    fetcher = _fetcher(httpx.MockTransport(handler))

    assert await fetcher.fetch_title("http://example.org/") == "example.org"


async def test_unusual_ports_and_literal_private_ips_are_refused() -> None:
    """SSRF: only web ports and public addresses."""
    transport = httpx.MockTransport(lambda r: _html("<title>No</title>"))
    fetcher = _fetcher(transport)

    assert await fetcher.fetch_title("http://example.org:22/") == "example.org"
    assert (
        await fetcher.fetch_title("http://169.254.169.254/latest") == "169.254.169.254"
    )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            404, content=b"<title>Gone</title>", headers={"content-type": "text/html"}
        ),
        httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        ),
        httpx.Response(500),
    ],
)
async def test_errors_and_non_html_fall_back_to_the_host(
    response: httpx.Response,
) -> None:
    """UF-WEB-07 2e: the domain is used."""
    transport = httpx.MockTransport(lambda r: response)

    assert (
        await _fetcher(transport).fetch_title("https://example.org/f") == "example.org"
    )


async def test_network_errors_fall_back_to_the_host() -> None:
    """UF-WEB-07 2e: timeouts and connection errors never fail link creation."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    assert (
        await _fetcher(httpx.MockTransport(handler)).fetch_title("https://example.org/")
        == "example.org"
    )


async def test_only_the_first_512_kb_are_read() -> None:
    """A title after 512 KB is not found."""
    body = "<p>" + "a" * (600 * 1024) + "</p><title>Late</title>"
    transport = httpx.MockTransport(lambda r: _html(body))

    assert (
        await _fetcher(transport).fetch_title("https://example.org/big")
        == "example.org"
    )
