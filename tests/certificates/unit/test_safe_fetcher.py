"""SSRF rules of the certificate PDF download."""

from app.modules.certificates.domain.errors import (
    CertificateDownloadError,
    UnsafeCertificateUrlError,
)
from app.modules.certificates.infrastructure.safe_fetcher import (
    SafeCertificateFetcher,
    check_url,
    is_public,
)

import httpx
import pytest


async def public(host: str) -> list[str]:
    """Resolver: a public address for every name."""
    return ["93.184.216.34"]


def fetcher(
    handler: httpx.MockTransport | None = None,
    *,
    resolver: object = public,
    max_bytes: int = 1000,
) -> SafeCertificateFetcher:
    """A fetcher over a mock transport."""
    transport = handler or httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"%PDF")
    )
    return SafeCertificateFetcher(
        resolver=resolver,  # type: ignore[arg-type]
        transport=transport,
        max_bytes=max_bytes,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://cert.uzbmb.uz/a.pdf",
        "https://uzbmb.uz.evil.com/a.pdf",
        "https://evil.com/uzbmb.uz",
        "https://notuzbmb.uz/a.pdf",
        "https://user@cert.uzbmb.uz/a.pdf",
        "https://cert.uzbmb.uz:8443/a.pdf",
        "https://127.0.0.1/a.pdf",
        "ftp://cert.uzbmb.uz/a.pdf",
        "file:///etc/passwd",
    ],
)
async def test_urls_outside_the_issuer_are_rejected(url: str) -> None:
    """Only https on uzbmb.uz or *.uzbmb.uz (port 443, no credentials) passes."""
    with pytest.raises(UnsafeCertificateUrlError):
        check_url(url)
    with pytest.raises(UnsafeCertificateUrlError):
        await fetcher().fetch(url)


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "127.0.0.1",
        "169.254.169.254",
        "192.168.1.1",
        "::1",
        "::ffff:10.0.0.1",
        "fc00::1",
    ],
)
def test_private_addresses_are_not_public(address: str) -> None:
    """Loopback, link-local, private and mapped private addresses are refused."""
    assert not is_public(address)


async def test_a_host_that_resolves_to_a_private_address_is_rejected() -> None:
    """DNS pointing an issuer name inside the network is caught."""

    async def inside(host: str) -> list[str]:
        return ["93.184.216.34", "10.0.0.7"]

    with pytest.raises(UnsafeCertificateUrlError):
        await fetcher(resolver=inside).fetch("https://cert.uzbmb.uz/a.pdf")


async def test_the_connection_goes_to_the_checked_address_with_the_host_name() -> None:
    """The request targets the resolved IP; Host and SNI keep the issuer's name."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"%PDF-1.4")

    got = await fetcher(httpx.MockTransport(handle)).fetch(
        "https://cert.uzbmb.uz/x/a%20b.pdf?t=1"
    )

    request = seen[0]
    assert (request.url.host, request.headers["host"]) == (
        "93.184.216.34",
        "cert.uzbmb.uz",
    )
    assert request.extensions["sni_hostname"] == "cert.uzbmb.uz"
    assert (got.name, got.data) == ("a b.pdf", b"%PDF-1.4")


async def test_a_redirect_to_another_host_is_refused() -> None:
    """A 302 off the issuer's host is not followed."""
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            302, headers={"location": "https://other.uzbmb.uz/a.pdf"}
        )
    )

    with pytest.raises(UnsafeCertificateUrlError):
        await fetcher(transport).fetch("https://cert.uzbmb.uz/a.pdf")


async def test_a_redirect_on_the_same_host_is_followed() -> None:
    """The same host may redirect to another path."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a.pdf":
            return httpx.Response(301, headers={"location": "/b.pdf"})
        return httpx.Response(200, content=b"%PDF")

    got = await fetcher(httpx.MockTransport(handle)).fetch(
        "https://cert.uzbmb.uz/a.pdf"
    )

    assert got.name == "b.pdf"


async def test_a_redirect_loop_stops() -> None:
    """At most three redirects are followed."""
    transport = httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"location": "/a.pdf"})
    )

    with pytest.raises(UnsafeCertificateUrlError):
        await fetcher(transport).fetch("https://cert.uzbmb.uz/a.pdf")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"x" * 2000),
        httpx.Response(200, headers={"content-length": "999999"}, content=b"x"),
        httpx.Response(404),
    ],
)
async def test_big_or_failed_downloads_raise(response: httpx.Response) -> None:
    """A body over the cap (declared or streamed) and non-200 answers fail."""
    with pytest.raises(CertificateDownloadError):
        await fetcher(httpx.MockTransport(lambda r: response)).fetch(
            "https://cert.uzbmb.uz/a.pdf"
        )
