"""SSRF-safe download of a ChatGPT file parameter for `upload_file`.

The URL comes from the model host, so it is untrusted input. Only https on port 443
to an allowlisted host (`IHSP_MCP__UPLOAD_HOSTS`) is fetched, with no credentials in
the URL. The host is resolved by us and must resolve to public addresses only; the
connection goes to that address (with the Host header and SNI of the name), so a
second DNS answer cannot redirect it. Redirects are followed by hand and every hop is
checked again. The body is read in a stream and cut at the size cap.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit

from app.interfaces.mcp.errors import (
    McpUploadDownloadFailedError,
    McpUploadTooLargeError,
    McpUploadUrlNotAllowedError,
)

import httpx

MAX_REDIRECTS = 3
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
Resolver = Callable[[str], Awaitable[list[str]]]
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True, slots=True)
class Downloaded:
    """A downloaded body and the name taken from the URL path."""

    name: str
    data: bytes


async def system_resolver(host: str) -> list[str]:
    """Resolve a host name to its addresses with the system resolver."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise McpUploadDownloadFailedError(support_details="dns failed") from exc
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


def parse_hosts(value: str) -> tuple[str, ...]:
    """Split the setting: lower-case names, `*.suffix` for sub-domains."""
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    """True when the host equals an entry or sits under a `*.suffix` entry."""
    for entry in allowed:
        if entry.startswith("*."):
            if host.endswith(entry[1:]) and len(host) > len(entry) - 1:
                return True
        elif host == entry:
            return True
    return False


def _unsafe(details: str) -> McpUploadUrlNotAllowedError:
    return McpUploadUrlNotAllowedError(support_details=details)


def check_url(url: str, allowed: tuple[str, ...]) -> tuple[str, str]:
    """Return (host, path with query) of an allowed URL, or raise."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError as exc:
        raise _unsafe("malformed url") from exc
    if parts.scheme != "https" or parts.username or parts.password:
        raise _unsafe("not a plain https url")
    if port not in (None, 443) or not host or not host.isascii():
        raise _unsafe("port or host not allowed")
    if not host_allowed(host, allowed):
        raise _unsafe("host is not on the allowlist")
    path = parts.path or "/"
    return host, path + (f"?{parts.query}" if parts.query else "")


def _file_name(path: str) -> str:
    last = unquote(path.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1])
    return last or "upload"


class SafeUploadFetcher:
    """Downloads one allowlisted https URL under the rules above."""

    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        max_bytes: int,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Store the allowlist, size cap, resolver and transport (both replaceable)."""
        self._allowed = allowed_hosts
        self._max_bytes = max_bytes
        self._resolver = resolver
        self._transport = transport

    async def fetch(self, url: str) -> Downloaded:
        """Download the file; every hop is checked again."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host, path = check_url(current, self._allowed)
            address = await self._public_address(host)
            result = await self._get_once(host, path, address)
            if isinstance(result, Downloaded):
                return result
            current = urljoin(f"https://{host}{path}", result)
        raise _unsafe("too many redirects")

    async def _public_address(self, host: str) -> str:
        addresses = await self._resolver(host)
        if not addresses or not all(is_public(a) for a in addresses):
            raise _unsafe("host resolves to a non-public address")
        return addresses[0]

    async def _get_once(self, host: str, path: str, address: str) -> Downloaded | str:
        """Return the file, or the Location of a redirect."""
        ip_host = f"[{address}]" if ":" in address else address
        request = httpx.Request(
            "GET",
            f"https://{ip_host}{path}",
            headers={"Host": host, "Accept": "*/*"},
            extensions={"sni_hostname": host},
        )
        async with httpx.AsyncClient(
            transport=self._transport, timeout=_TIMEOUT, follow_redirects=False
        ) as client:
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise McpUploadDownloadFailedError(
                    support_details=f"transport {type(exc).__name__}"
                ) from exc
            try:
                return await self._read(response, path)
            except httpx.HTTPError as exc:
                raise McpUploadDownloadFailedError(
                    support_details=f"transport {type(exc).__name__}"
                ) from exc
            finally:
                await response.aclose()

    def _too_large(self) -> McpUploadTooLargeError:
        return McpUploadTooLargeError(params={"max_bytes": self._max_bytes})

    async def _read(self, response: httpx.Response, path: str) -> Downloaded | str:
        if response.status_code in _REDIRECTS:
            location: str | None = response.headers.get("location")
            if not location:
                raise McpUploadDownloadFailedError(support_details="redirect no url")
            return location
        if response.status_code != 200:
            raise McpUploadDownloadFailedError(
                support_details=f"HTTP {response.status_code}"
            )
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_bytes:
            raise self._too_large()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > self._max_bytes:
                raise self._too_large()
        return Downloaded(name=_file_name(path), data=bytes(data))
