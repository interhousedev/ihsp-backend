"""SSRF-safe download of certificate PDFs from the issuer's site (uzbmb.uz).

Only https on ``uzbmb.uz`` or a subdomain is allowed. The name is resolved here, every
address must be public, and the connection goes to the checked address (the TLS
name stays the host's), so a DNS answer cannot change between check and use. A
redirect is followed only to the same host, and the body is capped.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import unquote, urljoin, urlsplit

from app.modules.certificates.domain.errors import (
    CertificateDownloadError,
    UnsafeCertificateUrlError,
)
from app.modules.certificates.ports.fetcher import FetchedFile

import httpx

ISSUER_DOMAIN = "uzbmb.uz"
MAX_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
Resolver = Callable[[str], Awaitable[list[str]]]
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


async def system_resolver(host: str) -> list[str]:
    """Resolve a host name to its addresses with the system resolver."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise CertificateDownloadError(support_details="dns failed") from exc
    return list(dict.fromkeys(str(info[4][0]).split("%", 1)[0] for info in infos))


def is_public(address: str) -> bool:
    """True for a globally routable unicast address (IPv4-mapped IPv6 unwrapped)."""
    try:
        ip: IpAddress = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _unsafe(details: str) -> UnsafeCertificateUrlError:
    return UnsafeCertificateUrlError(support_details=details)


def check_url(url: str) -> tuple[str, str]:
    """Return (host, path with query) of an allowed URL, or raise."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError as exc:
        raise _unsafe("malformed url") from exc
    if parts.scheme != "https" or parts.username or parts.password:
        raise _unsafe("not a plain https url")
    if port not in (None, 443) or not host.isascii():
        raise _unsafe("port or host not allowed")
    if host != ISSUER_DOMAIN and not host.endswith("." + ISSUER_DOMAIN):
        raise _unsafe("host is not the issuer's")
    path = parts.path or "/"
    return host, path + (f"?{parts.query}" if parts.query else "")


def _file_name(path: str) -> str:
    last = unquote(path.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1])
    return last or "certificate.pdf"


class SafeCertificateFetcher:
    """Implements ``CertificateFetcher`` with the rules above."""

    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        """Store the resolver (replaceable in tests), transport and size cap."""
        self._resolver = resolver
        self._transport = transport
        self._max_bytes = max_bytes

    async def fetch(self, url: str) -> FetchedFile:
        """Download the file; every hop is checked again."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host, path = check_url(current)
            address = await self._public_address(host)
            location = await self._get_once(host, path, address)
            if isinstance(location, FetchedFile):
                return location
            current = urljoin(f"https://{host}{path}", location)
            if urlsplit(current).hostname != host:
                raise _unsafe("redirect leaves the host")
        raise _unsafe("too many redirects")

    async def _public_address(self, host: str) -> str:
        addresses = await self._resolver(host)
        if not addresses or not all(is_public(a) for a in addresses):
            raise _unsafe("host resolves to a non-public address")
        return addresses[0]

    async def _get_once(self, host: str, path: str, address: str) -> FetchedFile | str:
        """Return the file, or the Location of a redirect."""
        ip_host = f"[{address}]" if ":" in address else address
        request = httpx.Request(
            "GET",
            f"https://{ip_host}{path}",
            headers={"Host": host, "Accept": "application/pdf,*/*;q=0.5"},
            extensions={"sni_hostname": host},
        )
        async with httpx.AsyncClient(
            transport=self._transport, timeout=_TIMEOUT, follow_redirects=False
        ) as client:
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise CertificateDownloadError(
                    support_details=f"transport {type(exc).__name__}"
                ) from exc
            try:
                return await self._read(response, path)
            finally:
                await response.aclose()

    async def _read(self, response: httpx.Response, path: str) -> FetchedFile | str:
        if response.status_code in _REDIRECTS:
            location: str | None = response.headers.get("location")
            if not location:
                raise CertificateDownloadError(support_details="redirect without url")
            return location
        if response.status_code != 200:
            raise CertificateDownloadError(
                support_details=f"HTTP {response.status_code}"
            )
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_bytes:
            raise CertificateDownloadError(support_details="file too large")
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > self._max_bytes:
                raise CertificateDownloadError(support_details="file too large")
        return FetchedFile(name=_file_name(path), data=bytes(data))
