"""NB-18, NB-19: the SSRF-safe fetcher of URL sources (§ 3.2.1, § 3.7, § 6.3)."""

import asyncio
import io
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.modules.notebooks.domain.errors import SourceReadError
from app.modules.notebooks.infrastructure import web_fetcher
from app.modules.notebooks.infrastructure.web_fetcher import (
    HttpWebFetcher,
    is_public_address,
)
from app.modules.notebooks.ports.web_fetcher import FetchedPage

import httpx
import pytest
from pypdf import PdfReader, PdfWriter

PUBLIC = "93.184.216.34"
PUBLIC_2 = "151.101.1.69"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
HTML = "text/html; charset=utf-8"


# - - - Helpers - - -


class FakeResolver:
    """A DNS resolver with a table; unknown names get the default answer."""

    def __init__(
        self,
        table: dict[str, list[str]] | None = None,
        default: list[str] | None = None,
    ) -> None:
        self.table = table or {}
        self.default = [PUBLIC] if default is None else default
        self.calls: list[str] = []

    async def __call__(self, host: str) -> list[str]:
        self.calls.append(host)
        return self.table.get(host, self.default)


class Web:
    """A fetcher on a mock transport; keeps the requests it sent."""

    def __init__(
        self,
        handler: Callable[[httpx.Request], httpx.Response] | None = None,
        table: dict[str, list[str]] | None = None,
        default: list[str] | None = None,
        **options: Any,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self.resolver = FakeResolver(table, default)
        self._handler = handler or (lambda request: page("<p>ok</p>"))
        self.fetcher = HttpWebFetcher(
            resolver=self.resolver,
            transport=httpx.MockTransport(self._handle),
            **options,
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    async def fetch(self, url: str) -> FetchedPage:
        return await self.fetcher.fetch(url)

    async def failure(self, url: str) -> SourceReadError:
        with pytest.raises(SourceReadError) as caught:
            await self.fetcher.fetch(url)
        return caught.value


def page(
    body: str | bytes = "",
    status: int = 200,
    content_type: str | None = HTML,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """A response; `content_type=None` leaves the header out."""
    content = body.encode() if isinstance(body, str) else body
    fields = dict(headers or {})
    if content_type is not None:
        fields["content-type"] = content_type
    return httpx.Response(status, content=content, headers=fields)


def redirect(
    location: str, status: int = 302, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, headers={"location": location, **(headers or {})})


class FakeStream:
    """What httpcore exposes as the `network_stream` extension."""

    def __init__(self, peer: str) -> None:
        self.peer = peer

    def get_extra_info(self, info: str) -> object:
        return (self.peer, 443) if info == "server_addr" else None


def make_pdf(pages: list[str], title: str | None = None) -> bytes:
    """A small valid PDF with one line of text per page (no parentheses in text)."""
    count = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode()
        objects[4 + 2 * index] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {5 + 2 * index} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>"
        ).encode()
        objects[5 + 2 * index] = (
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
    extra = ""
    if title is not None:
        objects[4 + 2 * count] = f"<< /Title ({title}) >>".encode()
        extra = f" /Info {4 + 2 * count} 0 R"
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    size = max(objects) + 1
    xref_at = len(out)
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R{extra} >>\n".encode()
    out += f"startxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def pdf_response(data: bytes) -> httpx.Response:
    return page(data, content_type="application/pdf")


# - - - Success - - -


async def test_html_page_gives_title_text_and_final_url() -> None:
    """NB-18: an HTML page is read into its title and main text."""
    markup = (
        "<html><head><title>Cell biology</title><style>p{}</style></head><body>"
        "<nav>Menu</nav><main><h1>Cells</h1><p>The cell is the unit of life.</p>"
        "</main><footer>Contact</footer></body></html>"
    )
    web = Web(lambda request: page(markup))

    result = await web.fetch("https://example.org/biology/cells")

    assert result == FetchedPage(
        url="https://example.org/biology/cells",
        title="Cell biology",
        text="# Cells\n\nThe cell is the unit of life.",
        content_type="text/html",
    )


async def test_plain_text_page_is_returned_as_text() -> None:
    """NB-18: text/plain is the decoded text."""
    web = Web(lambda request: page("Line one\nLine two\n", content_type="text/plain"))

    result = await web.fetch("https://example.org/notes.txt")

    assert result.text == "Line one\nLine two\n"
    assert result.title is None
    assert result.content_type == "text/plain"
    assert result.pages == ()


async def test_pdf_gives_text_title_and_page_offsets() -> None:
    """NB-18: a PDF is read page by page; pages are joined by a newline."""
    data = make_pdf(["First page", "Second page", "Third page"], title="Biology 10")
    web = Web(lambda request: pdf_response(data))

    result = await web.fetch("https://example.org/book.pdf")

    assert result.content_type == "application/pdf"
    assert result.title == "Biology 10"
    assert len(result.pages) == 3
    assert result.pages[0] == 0
    for offset, expected in zip(
        result.pages, ["First page", "Second page", "Third page"], strict=True
    ):
        assert result.text[offset:].startswith(expected)


async def test_pdf_without_a_title_has_none() -> None:
    """NB-18: no document title: None."""
    web = Web(lambda request: pdf_response(make_pdf(["Only page"])))

    result = await web.fetch("https://example.org/a.pdf")

    assert result.title is None
    assert result.text.strip() == "Only page"


async def test_pdf_without_text_is_empty_not_an_error() -> None:
    """NB-18: an image-only PDF gives empty text (the pipeline reports no_text)."""
    web = Web(lambda request: pdf_response(make_pdf(["", ""])))

    result = await web.fetch("https://example.org/scan.pdf")

    assert result.text == ""
    assert result.pages == ()


async def test_page_without_text_is_empty_not_an_error() -> None:
    """NB-18: an HTML page with no readable text gives empty text."""
    web = Web(lambda request: page("<script>x()</script>"))

    result = await web.fetch("https://example.org/app")

    assert result.text == ""


async def test_pdf_is_cut_at_the_page_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """NB-18: at most PDF_MAX_PAGES pages are read."""
    monkeypatch.setattr(web_fetcher, "PDF_MAX_PAGES", 2)
    data = make_pdf(["Page one", "Page two", "Page three", "Page four"])
    web = Web(lambda request: pdf_response(data))

    result = await web.fetch("https://example.org/long.pdf")

    assert len(result.pages) == 2
    assert "Page three" not in result.text


async def test_pdf_is_cut_at_the_character_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NB-18: the text is cut at PDF_MAX_CHARS and the offsets stay inside it."""
    monkeypatch.setattr(web_fetcher, "PDF_MAX_CHARS", 15)
    data = make_pdf(["Page one", "Page two", "Page three"])
    web = Web(lambda request: pdf_response(data))

    result = await web.fetch("https://example.org/long.pdf")

    assert len(result.text) <= 15
    assert all(offset < len(result.text) for offset in result.pages)
    assert result.text.startswith("Page one")


def test_pdf_limits_are_the_documented_ones() -> None:
    """NB-18: 300 pages and 2 000 000 characters, 2 MB and 10 s by default."""
    fetcher = HttpWebFetcher()

    assert web_fetcher.PDF_MAX_PAGES == 300
    assert web_fetcher.PDF_MAX_CHARS == 2_000_000
    assert fetcher.max_bytes == 2_000_000
    assert fetcher.timeout_seconds == 10.0


@pytest.mark.parametrize(
    "data",
    [b"%PDF-1.4 this is not a pdf", b"", b"<html>not a pdf</html>"],
)
async def test_broken_pdf_is_unsupported(data: bytes) -> None:
    """NB-18: a damaged PDF is unsupported_type."""
    web = Web(lambda request: pdf_response(data))

    error = await web.failure("https://example.org/broken.pdf")

    assert error.failure == "unsupported_type"


async def test_encrypted_pdf_is_unsupported() -> None:
    """NB-18: a PDF that needs a password is unsupported_type."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["Secret"]))))
    writer.encrypt("secret", algorithm="AES-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    web = Web(lambda request: pdf_response(buffer.getvalue()))

    error = await web.failure("https://example.org/locked.pdf")

    assert error.failure == "unsupported_type"


# - - - The request - - -


async def test_request_has_the_fixed_user_agent_and_accept_header() -> None:
    """NB-18: a fixed User-Agent and an Accept limited to the three types."""
    web = Web()

    await web.fetch("https://example.org/")

    headers = web.requests[0].headers
    assert headers["user-agent"] == "IHSP-Notebooks/1.0"
    assert headers["accept"] == "text/html, text/plain, application/pdf"
    assert web.requests[0].method == "GET"


async def test_request_carries_no_cookie_or_credentials() -> None:
    """NB-18: no cookies, no authorization, no referer."""
    web = Web()

    await web.fetch("https://example.org/")

    headers = web.requests[0].headers
    assert "cookie" not in headers
    assert "authorization" not in headers
    assert "referer" not in headers


async def test_connects_to_the_resolved_ip_with_the_real_name_in_host_and_sni() -> None:
    """NB-19: the URL host is the validated IP; Host and SNI are the real name."""
    web = Web()

    await web.fetch("https://Example.org/path?q=1")

    request = web.requests[0]
    assert request.url.host == PUBLIC
    assert request.url.scheme == "https"
    assert request.headers["host"] == "example.org"
    assert request.extensions["sni_hostname"] == "example.org"
    assert request.url.path == "/path"
    assert request.url.query == b"q=1"


async def test_plain_http_sends_no_sni() -> None:
    """NB-19: the TLS server name is only for https."""
    web = Web()

    await web.fetch("http://example.org/")

    request = web.requests[0]
    assert request.url.host == PUBLIC
    assert request.headers["host"] == "example.org"
    assert "sni_hostname" not in request.extensions


async def test_ipv6_address_is_connected_in_brackets() -> None:
    """NB-19: an IPv6 answer is used as the URL host."""
    web = Web(table={"example.org": [PUBLIC_V6]})

    await web.fetch("https://example.org/")

    assert web.requests[0].url.host == PUBLIC_V6
    assert web.requests[0].headers["host"] == "example.org"


@pytest.mark.parametrize(
    "url", ["http://example.org:80/a", "https://example.org:443/a"]
)
async def test_explicit_ports_80_and_443_are_allowed(url: str) -> None:
    """NB-19: ports 80 and 443 pass, explicit or not; Host omits a default port."""
    web = Web()

    await web.fetch(url)

    assert web.requests[0].headers["host"] == "example.org"


async def test_http_on_port_443_keeps_the_port_in_the_host_header() -> None:
    """NB-19: the port rule ignores the scheme; a non-default port is sent."""
    web = Web()

    await web.fetch("http://example.org:443/a")

    assert web.requests[0].headers["host"] == "example.org:443"


async def test_fragment_is_neither_sent_nor_kept() -> None:
    """NB-18: the fragment is dropped from the request and from the final URL."""
    web = Web()

    result = await web.fetch("https://example.org/a#section")

    assert result.url == "https://example.org/a"
    assert web.requests[0].url.fragment == ""


async def test_surrounding_white_space_is_ignored() -> None:
    """NB-18: a pasted URL with spaces around it works."""
    web = Web()

    result = await web.fetch("  https://example.org/a \n")

    assert result.url == "https://example.org/a"


async def test_internationalised_host_is_resolved_in_ascii() -> None:
    """NB-19: the resolver, Host and SNI get the IDNA form of the name."""
    web = Web()

    await web.fetch("https://пример.рф/")

    assert web.resolver.calls == ["xn--e1afmkfd.xn--p1ai"]
    assert web.requests[0].headers["host"] == "xn--e1afmkfd.xn--p1ai"


async def test_trailing_dot_and_case_are_normalised_before_resolving() -> None:
    """NB-19: Example.ORG. is resolved as example.org."""
    web = Web()

    await web.fetch("https://Example.ORG./")

    assert web.resolver.calls == ["example.org"]


async def test_next_validated_address_is_tried_when_the_first_refuses() -> None:
    """NB-19: only validated addresses are tried, one after another."""
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.host)
        if request.url.host == PUBLIC:
            raise httpx.ConnectError("refused", request=request)
        return page("<p>second</p>")

    web = Web(handler, table={"example.org": [PUBLIC, PUBLIC_2]})

    result = await web.fetch("https://example.org/")

    assert attempts == [PUBLIC, PUBLIC_2]
    assert result.text == "second"
    assert web.resolver.calls == ["example.org"]


async def test_all_addresses_refusing_is_fetch_failed() -> None:
    """NB-19: nothing connects: fetch_failed."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    web = Web(handler, table={"example.org": [PUBLIC, PUBLIC_2]})

    error = await web.failure("https://example.org/")

    assert error.failure == "fetch_failed"


# - - - SSRF: blocked targets - - -

BLOCKED_ADDRESSES = [
    "http://127.0.0.1/",
    "http://127.0.0.1:80/admin",
    "http://127.1/",
    "http://0/",
    "http://0.0.0.0/",
    "http://0x7f000001/",
    "http://0x7f.0.0.1/",
    "http://2130706433/",
    "http://017700000001/",
    "http://0177.0.0.1/",
    "http://10.0.0.5/",
    "http://172.16.0.1/",
    "http://172.31.255.255/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.169.254:80/",
    "http://100.64.0.1/",
    "http://100.100.100.200/",
    "http://224.0.0.1/",
    "http://240.0.0.1/",
    "http://255.255.255.255/",
    "http://[::1]/",
    "http://[::]/",
    "http://[fd00::1]/",
    "http://[fd00:ec2::254]/",
    "http://[fe80::1]/",
    "http://[ff02::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://[::ffff:7f00:1]/",
    "http://[::ffff:10.0.0.1]/",
    "http://[::ffff:169.254.169.254]/",
    "http://[::127.0.0.1]/",
    "http://[2002:7f00:1::]/",
    "http://[2002:0a00:0001::1]/",
    "http://[64:ff9b::7f00:1]/",
    "http://[64:ff9b::a9fe:a9fe]/",
    "http://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/",
    "https://[::1]:443/",
]


@pytest.mark.parametrize("url", BLOCKED_ADDRESSES)
async def test_private_ip_literals_are_forbidden_without_dns_or_request(
    url: str,
) -> None:
    """NB-19, § 3.7: private, loopback, link-local and wrapped IPs are refused."""
    web = Web(default=[PUBLIC])

    error = await web.failure(url)

    assert error.failure == "forbidden"
    assert web.requests == []
    assert web.resolver.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://LOCALHOST/",
        "http://localhost./",
        "http://localhost:80/",
        "http://app.localhost/",
        "http://ip6-localhost/",
        "http://metadata/",
        "http://intranet/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://printer.local/",
        "http://host.localdomain/",
        "http://router.home.arpa/",
        "http://nas.lan/",
    ],
)
async def test_internal_names_are_forbidden_without_dns(url: str) -> None:
    """NB-19: localhost-like and single-label names never reach the resolver."""
    web = Web()

    error = await web.failure(url)

    assert error.failure == "forbidden"
    assert web.requests == []
    assert web.resolver.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://999.1.1.1/",
        "http://1.2.3.4.5/",
        "http://256.256.256.256/",
        "http://1.2.3.08/",
        "http://example.123/",
        "http://0xZZ/",
    ],
)
async def test_hosts_that_look_like_broken_ip_addresses_are_forbidden(url: str) -> None:
    """NB-19: a host ending in a number must be a valid IP address."""
    web = Web()

    error = await web.failure(url)

    assert error.failure == "forbidden"
    assert web.requests == []


@pytest.mark.parametrize(
    "answer",
    [
        ["127.0.0.1"],
        ["10.1.2.3"],
        ["172.20.0.9"],
        ["192.168.0.10"],
        ["169.254.169.254"],
        ["100.64.12.1"],
        ["0.0.0.0"],
        ["224.0.0.251"],
        ["::1"],
        ["fd12:3456::1"],
        ["fe80::1"],
        ["fe80::1%eth0"],
        ["::ffff:10.0.0.1"],
        ["2002:c0a8:0101::1"],
        [PUBLIC, "10.0.0.5"],
        [PUBLIC_V6, "::1"],
        ["not-an-address"],
    ],
)
async def test_names_that_resolve_to_non_public_addresses_are_forbidden(
    answer: list[str],
) -> None:
    """NB-19: if ANY resolved address is not public, nothing is requested."""
    web = Web(table={"evil.example": answer})

    error = await web.failure("https://evil.example/")

    assert error.failure == "forbidden"
    assert web.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org:8080/",
        "http://example.org:8000/",
        "https://example.org:8443/",
        "http://example.org:22/",
        "http://example.org:6379/",
        "http://example.org:5432/",
        "http://example.org:0/",
        "http://example.org:65535/",
        "http://example.org:99999/",
        "http://example.org:abc/",
        "http://127.0.0.1:8080/",
    ],
)
async def test_ports_other_than_80_and_443_are_forbidden(url: str) -> None:
    """NB-19: only ports 80 and 443."""
    web = Web()

    error = await web.failure(url)

    assert error.failure == "forbidden"
    assert web.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file://localhost/etc/passwd",
        "ftp://example.org/file.txt",
        "gopher://example.org/",
        "ws://example.org/",
        "javascript:alert(1)",
        "data:text/html,<p>x</p>",
        "//example.org/path",
        "example.org/path",
        "HTTP-ish://example.org/",
        "",
        "   ",
    ],
)
async def test_other_schemes_and_scheme_less_urls_are_forbidden(url: str) -> None:
    """NB-19: only http and https."""
    web = Web()

    error = await web.failure(url)

    assert error.failure == "forbidden"
    assert web.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pass@example.org/",
        "https://user@example.org/",
        "http://:pass@example.org/",
        "http://@example.org/",
        "http://example.org:80@evil.example/",
        "http://example.org@127.0.0.1/",
    ],
)
async def test_credentials_in_the_url_are_forbidden(url: str) -> None:
    """NB-19: no user info, in any form."""
    web = Web()

    error = await web.failure(url)

    assert error.failure == "forbidden"
    assert web.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://exa mple.org/",
        "http://example.org/a b",
        "http://example.org/a\nb",
        "http://example.org\\@127.0.0.1/",
        "http://example.org/\x00",
        "http://[::1/",
        "http://a..b/",
        "http://-bad-.example/",
        "http://under score!.example/",
        "http://127%2e0%2e0%2e1/",
        "https://example.org/" + "a" * 2100,
        "http:///path",
        "http:example.org",
    ],
)
async def test_malformed_urls_are_forbidden(url: str) -> None:
    """NB-19: control characters, spaces, backslashes and broken hosts are refused."""
    web = Web()

    error = await web.failure(url)

    assert error.failure == "forbidden"
    assert web.requests == []


# - - - SSRF: is_public_address - - -


@pytest.mark.parametrize(
    "address",
    [
        "8.8.8.8",
        "1.1.1.1",
        PUBLIC,
        "172.15.255.255",
        "172.32.0.1",
        "100.63.255.255",
        "100.128.0.1",
        "2606:4700:4700::1111",
        PUBLIC_V6,
        "::ffff:8.8.8.8",
    ],
)
def test_public_addresses_are_public(address: str) -> None:
    """NB-19: ordinary global addresses pass."""
    assert is_public_address(address) is True


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.255.255.254",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.255.255",
        "169.254.169.254",
        "100.64.0.0",
        "100.127.255.255",
        "0.0.0.0",
        "224.0.0.1",
        "239.255.255.250",
        "240.0.0.1",
        "255.255.255.255",
        "192.0.2.1",
        "198.18.0.1",
        "::",
        "::1",
        "fc00::1",
        "fd00::1",
        "fe80::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:127.0.0.1",
        "::ffff:192.168.0.1",
        "::192.168.0.1",
        "2002:7f00:1::",
        "2002:a9fe:a9fe::",
        "2002:0808:0808::1",
        "64:ff9b::7f00:1",
        "64:ff9b::808:808",
        "64:ff9b::a00:1",
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",
        "fe80::1%eth0",
        "",
        "   ",
        "localhost",
        "example.org",
        "1.2.3",
        "1.2.3.4.5",
        "256.1.1.1",
        "0x7f000001",
    ],
)
def test_non_public_addresses_are_not_public(address: str) -> None:
    """NB-19, § 3.7: loopback, private, link-local, metadata, CGNAT, multicast, ..."""
    assert is_public_address(address) is False


# - - - DNS rebinding and the peer address - - -


async def test_host_is_resolved_once_and_the_validated_ip_is_the_one_used() -> None:
    """NB-19: DNS rebinding. A name that answers public first and private next is
    resolved once; the request goes to the first (validated) address."""
    calls = 0

    async def rebinding(host: str) -> list[str]:
        nonlocal calls
        calls += 1
        return [PUBLIC] if calls == 1 else ["169.254.169.254"]

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return page("<p>safe</p>")

    fetcher = HttpWebFetcher(resolver=rebinding, transport=httpx.MockTransport(handler))

    result = await fetcher.fetch("https://rebind.example/page")

    assert calls == 1
    assert result.text == "safe"
    assert [r.url.host for r in requests] == [PUBLIC]
    assert requests[0].headers["host"] == "rebind.example"
    assert requests[0].extensions["sni_hostname"] == "rebind.example"


async def test_retrying_another_address_does_not_resolve_again() -> None:
    """NB-19: trying the next address does not resolve the name again."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == PUBLIC:
            raise httpx.ConnectTimeout("slow", request=request)
        return page("<p>ok</p>")

    web = Web(handler, table={"example.org": [PUBLIC, PUBLIC_2]})

    await web.fetch("https://example.org/")

    assert web.resolver.calls == ["example.org"]


async def test_connection_to_another_address_than_validated_is_forbidden() -> None:
    """NB-19: the peer of the connection is checked against the validated address."""
    web = Web(
        lambda request: httpx.Response(
            200,
            content=b"<p>internal</p>",
            headers={"content-type": HTML},
            extensions={"network_stream": FakeStream("10.0.0.5")},
        )
    )

    error = await web.failure("https://example.org/")

    assert error.failure == "forbidden"


async def test_connection_to_the_validated_address_is_accepted() -> None:
    """NB-19: the check passes when the peer is the validated address."""
    web = Web(
        lambda request: httpx.Response(
            200,
            content=b"<p>fine</p>",
            headers={"content-type": HTML},
            extensions={"network_stream": FakeStream(PUBLIC)},
        )
    )

    result = await web.fetch("https://example.org/")

    assert result.text == "fine"


async def test_ipv4_mapped_peer_equals_the_validated_ipv4_address() -> None:
    """NB-19: a dual-stack socket that reports ::ffff:a.b.c.d is the same address."""
    web = Web(
        lambda request: httpx.Response(
            200,
            content=b"<p>fine</p>",
            headers={"content-type": HTML},
            extensions={"network_stream": FakeStream(f"::ffff:{PUBLIC}")},
        )
    )

    result = await web.fetch("https://example.org/")

    assert result.text == "fine"


async def test_each_hop_resolves_and_validates_its_own_host() -> None:
    """NB-19: redirect targets are resolved separately and connected by their own IP."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "first.example":
            return redirect("https://second.example/final")
        return page("<p>done</p>")

    web = Web(
        handler,
        table={"first.example": [PUBLIC], "second.example": [PUBLIC_2]},
    )

    result = await web.fetch("https://first.example/start")

    assert web.resolver.calls == ["first.example", "second.example"]
    assert [r.url.host for r in web.requests] == [PUBLIC, PUBLIC_2]
    assert result.url == "https://second.example/final"


async def test_resolver_failure_is_fetch_failed() -> None:
    """NB-18: a name that does not resolve is fetch_failed."""

    async def broken(host: str) -> list[str]:
        raise OSError("Name or service not known")

    fetcher = HttpWebFetcher(
        resolver=broken, transport=httpx.MockTransport(lambda r: page())
    )

    with pytest.raises(SourceReadError) as caught:
        await fetcher.fetch("https://nope.example/")

    assert caught.value.failure == "fetch_failed"


async def test_resolver_without_addresses_is_fetch_failed() -> None:
    """NB-18: an empty answer is fetch_failed."""
    web = Web(table={"empty.example": []})

    error = await web.failure("https://empty.example/")

    assert error.failure == "fetch_failed"
    assert web.requests == []


# - - - Redirects - - -


async def test_relative_redirect_is_followed_and_gives_the_final_url() -> None:
    """NB-18: Location may be relative; the final URL is reported."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return redirect("/new/page?x=1", status=301)
        return page("<p>new</p>")

    web = Web(handler)

    result = await web.fetch("https://example.org/old")

    assert result.url == "https://example.org/new/page?x=1"
    assert result.text == "new"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_all_redirect_statuses_are_followed(status: int) -> None:
    """NB-18: 301, 302, 303, 307 and 308."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return redirect("/target", status=status)
        return page("<p>arrived</p>")

    web = Web(handler)

    result = await web.fetch("https://example.org/")

    assert result.text == "arrived"


def _chain(hops: int) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        step = int(request.url.path.strip("/") or 0)
        if step < hops:
            return redirect(f"/{step + 1}")
        return page("<p>end of chain</p>")

    return handler


async def test_three_redirects_are_followed() -> None:
    """NB-19: at most 3 redirects."""
    web = Web(_chain(3))

    result = await web.fetch("https://example.org/")

    assert result.text == "end of chain"
    assert len(web.requests) == 4


async def test_fourth_redirect_fails() -> None:
    """NB-19: the 4th redirect is refused."""
    web = Web(_chain(4))

    error = await web.failure("https://example.org/")

    assert error.failure == "fetch_failed"
    assert len(web.requests) == 4


async def test_redirect_loop_fails() -> None:
    """NB-19: a redirect loop ends after the limit."""
    web = Web(lambda request: redirect("/again"))

    error = await web.failure("https://example.org/")

    assert error.failure == "fetch_failed"


async def test_redirect_without_location_fails() -> None:
    """NB-18: a 302 with no Location is fetch_failed."""
    web = Web(lambda request: httpx.Response(302))

    error = await web.failure("https://example.org/")

    assert error.failure == "fetch_failed"


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://[::ffff:10.0.0.1]/",
        "http://localhost/admin",
    ],
)
async def test_redirect_to_a_private_address_is_forbidden(location: str) -> None:
    """NB-19, § 6.3: a redirect to a private address is refused, not requested."""
    web = Web(lambda request: redirect(location))

    error = await web.failure("https://example.org/")

    assert error.failure == "forbidden"
    assert len(web.requests) == 1


async def test_redirect_to_a_name_that_resolves_privately_is_forbidden() -> None:
    """NB-19: the redirect target's DNS answer is validated too."""
    web = Web(
        lambda request: redirect("https://internal.example/secret"),
        table={"internal.example": ["10.0.0.7"]},
    )

    error = await web.failure("https://example.org/")

    assert error.failure == "forbidden"
    assert len(web.requests) == 1


@pytest.mark.parametrize(
    "location",
    [
        "file:///etc/passwd",
        "ftp://example.org/",
        "gopher://example.org/",
        "http://example.org:8080/",
        "http://user:pass@example.org/",
        "//127.0.0.1/",
    ],
)
async def test_redirect_to_a_forbidden_scheme_port_or_credentials(
    location: str,
) -> None:
    """NB-19: redirect targets go through the same URL checks."""
    web = Web(lambda request: redirect(location))

    error = await web.failure("https://example.org/")

    assert error.failure == "forbidden"
    assert len(web.requests) == 1


async def test_cookies_set_by_a_response_are_not_sent_back() -> None:
    """NB-18: no cookie jar: a Set-Cookie is never replayed on the next hop."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return redirect("/next", headers={"set-cookie": "sid=abc; Path=/"})
        return page("<p>ok</p>")

    web = Web(handler)

    await web.fetch("https://example.org/")

    assert len(web.requests) == 2
    assert all("cookie" not in request.headers for request in web.requests)


async def test_each_fetch_starts_without_cookies() -> None:
    """NB-18: a fresh client per fetch."""

    def handler(request: httpx.Request) -> httpx.Response:
        return page("<p>ok</p>", headers={"set-cookie": "sid=abc"})

    web = Web(handler)

    await web.fetch("https://example.org/")
    await web.fetch("https://example.org/")

    assert all("cookie" not in request.headers for request in web.requests)


# - - - Content types - - -


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "image/png",
        "image/svg+xml",
        "video/mp4",
        "application/octet-stream",
        "application/zip",
        "text/css",
        "text/javascript",
        "application/xhtml+xml",
        "application/msword",
        "",
        None,
    ],
)
async def test_other_content_types_are_unsupported(content_type: str | None) -> None:
    """NB-18: only text/html, text/plain and application/pdf."""
    web = Web(lambda request: page("data", content_type=content_type))

    error = await web.failure("https://example.org/file")

    assert error.failure == "unsupported_type"


@pytest.mark.parametrize(
    "content_type", ["TEXT/HTML", "text/html;charset=UTF-8", " text/html ; q=1"]
)
async def test_content_type_parameters_and_case_are_ignored(content_type: str) -> None:
    """NB-18: the media type is compared without parameters and case."""
    web = Web(lambda request: page("<p>ok</p>", content_type=content_type))

    result = await web.fetch("https://example.org/")

    assert result.content_type == "text/html"


async def test_unsupported_type_is_refused_before_the_body_is_read() -> None:
    """NB-18: a video is not downloaded."""
    pulled = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal pulled
        for _ in range(100):
            pulled += 1
            yield b"x" * 1000

    web = Web(
        lambda request: httpx.Response(
            200, content=body(), headers={"content-type": "video/mp4"}
        )
    )

    error = await web.failure("https://example.org/movie")

    assert error.failure == "unsupported_type"
    assert pulled == 0


# - - - Size - - -


async def test_body_over_the_limit_is_too_large_and_reading_stops() -> None:
    """NB-18: more than max_bytes is too_large; the stream is not read to the end."""
    pulled = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal pulled
        for _ in range(1000):
            pulled += 1
            yield b"x" * 1000

    web = Web(
        lambda request: httpx.Response(
            200, content=body(), headers={"content-type": "text/plain"}
        ),
        max_bytes=10_000,
    )

    error = await web.failure("https://example.org/big")

    assert error.failure == "too_large"
    assert pulled < 20


async def test_declared_length_over_the_limit_is_too_large_without_reading() -> None:
    """NB-18: a Content-Length over the limit is refused at once."""
    pulled = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal pulled
        pulled += 1
        yield b"x"

    web = Web(
        lambda request: httpx.Response(
            200,
            content=body(),
            headers={"content-type": "text/plain", "content-length": "5000"},
        ),
        max_bytes=1000,
    )

    error = await web.failure("https://example.org/big")

    assert error.failure == "too_large"
    assert pulled == 0


async def test_body_of_exactly_the_limit_is_accepted() -> None:
    """NB-18: 2 MB is allowed, one more byte is not."""
    web = Web(
        lambda request: page("a" * 1000, content_type="text/plain"), max_bytes=1000
    )

    result = await web.fetch("https://example.org/")

    assert result.text == "a" * 1000


async def test_one_byte_over_the_limit_is_too_large() -> None:
    """NB-18: the limit is exact."""
    web = Web(
        lambda request: page("a" * 1001, content_type="text/plain"), max_bytes=1000
    )

    error = await web.failure("https://example.org/")

    assert error.failure == "too_large"


# - - - Status codes and network errors - - -


@pytest.mark.parametrize(
    "status", [400, 401, 402, 403, 404, 410, 429, 451, 500, 502, 503]
)
async def test_http_errors_and_paywalls_are_fetch_failed(status: int) -> None:
    """NB-18: HTTP >= 400 (including 401/403 paywalls) is fetch_failed."""
    web = Web(lambda request: page("<p>Subscribe to read</p>", status=status))

    error = await web.failure("https://example.org/article")

    assert error.failure == "fetch_failed"


@pytest.mark.parametrize("status", [300, 304, 305])
async def test_other_3xx_without_redirect_meaning_are_fetch_failed(status: int) -> None:
    """NB-18: a 3xx that is not a redirect gives no page."""
    web = Web(lambda request: httpx.Response(status, headers={"location": "/x"}))

    error = await web.failure("https://example.org/")

    assert error.failure == "fetch_failed"


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("refused"),
        httpx.ReadError("reset"),
        httpx.RemoteProtocolError("bad response"),
        httpx.ReadTimeout("slow"),
        httpx.ConnectTimeout("slow"),
        httpx.PoolTimeout("slow"),
    ],
)
async def test_network_errors_are_fetch_failed(error: httpx.HTTPError) -> None:
    """NB-18: connection errors and timeouts are fetch_failed."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    web = Web(handler)

    caught = await web.failure("https://example.org/")

    assert caught.failure == "fetch_failed"


async def test_total_time_limit_is_enforced() -> None:
    """NB-19: a response that takes longer than the timeout is fetch_failed."""

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return page("<p>late</p>")

    fetcher = HttpWebFetcher(
        resolver=FakeResolver(),
        transport=httpx.MockTransport(slow),
        timeout_seconds=0.05,
    )

    with pytest.raises(SourceReadError) as caught:
        await fetcher.fetch("https://example.org/")

    assert caught.value.failure == "fetch_failed"


async def test_slow_body_counts_against_the_total_time() -> None:
    """NB-19: a body that trickles in is cut by the same limit."""

    async def trickle() -> AsyncIterator[bytes]:
        for _ in range(100):
            await asyncio.sleep(0.05)
            yield b"x"

    fetcher = HttpWebFetcher(
        resolver=FakeResolver(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=trickle(), headers={"content-type": "text/plain"}
            )
        ),
        timeout_seconds=0.2,
    )

    with pytest.raises(SourceReadError) as caught:
        await fetcher.fetch("https://example.org/")

    assert caught.value.failure == "fetch_failed"


# - - - Charset - - -


async def test_charset_from_the_header() -> None:
    """NB-18: the charset of the Content-Type header decodes the page."""
    body = "<p>Привет, мир</p>".encode("windows-1251")
    web = Web(
        lambda request: page(body, content_type="text/html; charset=windows-1251")
    )

    result = await web.fetch("https://example.org/")

    assert result.text == "Привет, мир"


async def test_charset_from_a_meta_tag_when_the_header_has_none() -> None:
    """NB-18: <meta charset> is used when the header does not say."""
    body = '<html><head><meta charset="koi8-r"></head><body><p>Привет</p></body></html>'
    web = Web(lambda request: page(body.encode("koi8-r"), content_type="text/html"))

    result = await web.fetch("https://example.org/")

    assert result.text == "Привет"


async def test_charset_from_a_meta_http_equiv() -> None:
    """NB-18: the old http-equiv form works too."""
    body = (
        '<meta http-equiv="Content-Type" content="text/html; charset=windows-1251">'
        "<p>Школа</p>"
    )
    web = Web(
        lambda request: page(body.encode("windows-1251"), content_type="text/html")
    )

    result = await web.fetch("https://example.org/")

    assert result.text == "Школа"


async def test_header_charset_wins_over_meta() -> None:
    """NB-18: the header comes first."""
    body = '<meta charset="windows-1251"><p>Привет</p>'.encode()
    web = Web(lambda request: page(body, content_type="text/html; charset=utf-8"))

    result = await web.fetch("https://example.org/")

    assert result.text == "Привет"


async def test_utf8_is_the_default_and_bad_bytes_are_replaced() -> None:
    """NB-18: no charset anywhere: UTF-8 with replacement characters."""
    body = b"<p>caf\xc3\xa9 \xff\xfe broken</p>"
    web = Web(lambda request: page(body, content_type="text/html"))

    result = await web.fetch("https://example.org/")

    assert result.text.startswith("café ")
    assert "�" in result.text


@pytest.mark.parametrize("label", ["no-such-charset", "base64", "rot13", "../etc"])
async def test_unknown_or_binary_charset_labels_fall_back_to_utf8(label: str) -> None:
    """NB-18: a bogus charset label never raises."""
    web = Web(
        lambda request: page("<p>ok é</p>", content_type=f"text/html; charset={label}")
    )

    result = await web.fetch("https://example.org/")

    assert result.text == "ok é"


async def test_utf8_bom_is_removed() -> None:
    """NB-18: a UTF-8 BOM does not end up in the text."""
    body = b"\xef\xbb\xbfhello"
    web = Web(lambda request: page(body, content_type="text/plain"))

    result = await web.fetch("https://example.org/a.txt")

    assert result.text == "hello"


async def test_utf16_bom_is_honoured() -> None:
    """NB-18: a UTF-16 text file with a BOM is decoded."""
    body = "Привет".encode("utf-16")
    web = Web(lambda request: page(body, content_type="text/plain"))

    result = await web.fetch("https://example.org/a.txt")

    assert result.text == "Привет"


async def test_plain_text_charset_from_the_header() -> None:
    """NB-18: text/plain obeys the header charset."""
    web = Web(
        lambda request: page(
            "Привет".encode("koi8-r"), content_type="text/plain; charset=koi8-r"
        )
    )

    result = await web.fetch("https://example.org/a.txt")

    assert result.text == "Привет"


# - - - Logging and errors - - -


class _LogSpy:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


async def test_logs_hold_the_host_and_the_status_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 3.7: no query string, no path, no body in logs."""
    spy = _LogSpy()
    monkeypatch.setattr(web_fetcher, "log", spy)
    web = Web(lambda request: page("<p>SECRET BODY</p>"))

    await web.fetch("https://example.org/private/path?token=SECRET#frag")

    assert spy.events == [
        ("notebooks_web_fetch", {"host": "example.org", "status": 200})
    ]
    for secret in ("SECRET", "token", "private", "frag"):
        assert secret not in repr(spy.events)


async def test_failures_are_logged_without_the_query_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 3.7: a failure log names the host and the machine code."""
    spy = _LogSpy()
    monkeypatch.setattr(web_fetcher, "log", spy)
    web = Web(lambda request: page("nope", status=404))

    await web.failure("https://example.org/private?token=SECRET")

    failure = (
        "notebooks_web_fetch_failed",
        {"host": "example.org", "failure": "fetch_failed"},
    )
    assert failure in spy.events
    assert "SECRET" not in repr(spy.events)
    assert "token" not in repr(spy.events)


async def test_blocked_url_is_logged_by_host_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 3.7: a refused URL is logged with its host, never its path or query."""
    spy = _LogSpy()
    monkeypatch.setattr(web_fetcher, "log", spy)
    web = Web()

    await web.failure("http://169.254.169.254/latest/meta-data/iam?key=SECRET")

    assert spy.events == [
        (
            "notebooks_web_fetch_failed",
            {"host": "169.254.169.254", "failure": "forbidden"},
        )
    ]


async def test_errors_carry_support_details_without_the_query() -> None:
    """NB-18: the error has a machine code and a short detail, not the URL."""
    web = Web(lambda request: page("nope", status=403))

    error = await web.failure("https://example.org/p?token=SECRET")

    assert error.failure == "fetch_failed"
    assert error.params == {"failure": "fetch_failed"}
    assert error.support_details is not None
    assert "SECRET" not in error.support_details
    assert "403" in error.support_details


async def test_http_response_body_is_not_executed_or_followed() -> None:
    """§ 3.7: links to internal addresses are only text; nothing else is requested."""
    markup = (
        '<p><a href="http://127.0.0.1/admin">admin</a></p>'
        '<img src="http://169.254.169.254/x"><iframe src="http://10.0.0.1/"></iframe>'
        '<meta http-equiv="refresh" content="0;url=http://127.0.0.1/">'
    )
    web = Web(lambda request: page(markup))

    result = await web.fetch("https://example.org/")

    assert result.text == "admin"
    assert len(web.requests) == 1
