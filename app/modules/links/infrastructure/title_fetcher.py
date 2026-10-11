"""Fetching the <title> of a page without letting users reach internal hosts.

Every hop (the first request and each redirect) resolves the host once, refuses
the hop if any address is not public, connects to the validated IP address only
(the real name goes into the `Host` header and the TLS server name) and checks the
peer address of the connection, so a DNS answer that changes between the check and
the request (DNS rebinding) cannot reach an internal service.
"""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from app.modules.links.domain.url_policy import host_of, is_public_ip

import httpx
import structlog

log = structlog.get_logger(__name__)

Resolver = Callable[[str], Awaitable[list[str]]]

TIMEOUT_SECONDS = 5.0
MAX_BYTES = 512 * 1024
MAX_REDIRECTS = 3
MAX_TITLE = 200
MAX_ADDRESSES = 4  # validated addresses tried one after another when connecting
FETCH_PORTS = (None, 80, 443, 8080, 8443)
REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class _TitleParser(HTMLParser):
    """Collects the text of the first <title> element."""

    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.done = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title" and not self.done:
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self.in_title:
            self.in_title = False
            self.done = True

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)


def parse_title(markup: str) -> str | None:
    """Return the collapsed text of the first <title>, or None."""
    parser = _TitleParser()
    parser.feed(markup)
    text = re.sub(r"\s+", " ", "".join(parser.parts)).strip()
    return text[:MAX_TITLE] or None


async def system_resolver(host: str) -> list[str]:
    """Resolve a host name to its IP addresses with the system resolver."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


@dataclass(frozen=True, slots=True)
class _Target:
    """A checked URL: where to connect and what to send."""

    scheme: str
    host: str
    port: int | None
    path: str  # path and query
    literal: bool
    addresses: tuple[str, ...]

    @property
    def host_header(self) -> str:
        default = 443 if self.scheme == "https" else 80
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port in (None, default) else f"{host}:{self.port}"

    def url_for(self, address: str) -> str:
        ip = f"[{address}]" if ":" in address else address
        port = "" if self.port is None else f":{self.port}"
        return f"{self.scheme}://{ip}{port}{self.path}"

    @property
    def extensions(self) -> dict[str, str]:
        if self.scheme == "https" and not self.literal:
            return {"sni_hostname": self.host}
        return {}


class HttpTitleFetcher:
    """Reads page titles over HTTP; private and loopback addresses are refused."""

    def __init__(
        self,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Store the DNS resolver and an optional transport (tests)."""
        self.resolver = resolver
        self.transport = transport

    async def fetch_title(self, url: str) -> str:
        """Return the page title, or the host name when it cannot be read."""
        fallback = host_of(url) or url
        try:
            title = await self._title(url)
        except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError):
            log.info("title_fetch_failed", host=fallback)
            return fallback
        return title or fallback

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=self.transport,
            trust_env=False,  # no proxy: the peer must be the validated address
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    async def _title(self, url: str) -> str | None:
        async with self._client() as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                target = await self._target(current)
                if target is None:
                    return None
                response, body = await self._hop(client, target)
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    current = urljoin(current, location)
                    continue
                return _title_of(response, body)
        return None

    async def _target(self, url: str) -> _Target | None:
        """Check the URL and resolve its host; None when the hop is refused."""
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        if parts.scheme not in ("http", "https") or not host or "@" in parts.netloc:
            return None
        if parts.port not in FETCH_PORTS:
            return None
        literal = _is_ip_literal(host)
        if literal:
            addresses: tuple[str, ...] = (host,)
        else:
            addresses = tuple(dict.fromkeys(await self.resolver(host)))
        if not addresses or not all(is_public_ip(a) for a in addresses):
            return None
        query = f"?{parts.query}" if parts.query else ""
        path = (parts.path or "/") + query
        return _Target(parts.scheme, host, parts.port, path, literal, addresses)

    async def _hop(
        self, client: httpx.AsyncClient, target: _Target
    ) -> tuple[httpx.Response, bytes]:
        """One request to the first validated address that accepts a connection."""
        failure: httpx.TransportError | None = None
        for address in target.addresses[:MAX_ADDRESSES]:
            try:
                return await _request(client, target, address)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                failure = exc
        raise httpx.ConnectError("connection failed") from failure


async def _request(
    client: httpx.AsyncClient, target: _Target, address: str
) -> tuple[httpx.Response, bytes]:
    async with client.stream(
        "GET",
        target.url_for(address),
        headers={**_HEADERS, "Host": target.host_header},
        extensions=target.extensions,
    ) as response:
        _check_peer(response, address)
        if response.status_code in REDIRECT_STATUSES:
            return response, b""
        return response, await _read_body(response)


def _same_address(peer: str, expected: str) -> bool:
    try:
        left = ipaddress.ip_address(peer.split("%", 1)[0])
        right = ipaddress.ip_address(expected)
    except ValueError:
        return False
    if isinstance(left, ipaddress.IPv6Address) and left.ipv4_mapped is not None:
        left = left.ipv4_mapped
    return left == right


def _check_peer(response: httpx.Response, address: str) -> None:
    """DNS-rebinding defence: the socket must be connected to the validated IP."""
    stream = response.extensions.get("network_stream")
    peer = stream.get_extra_info("server_addr") if stream is not None else None
    if peer and not _same_address(str(peer[0]), address):
        raise ValueError("connected to an address that was not validated")


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


_HEADERS = {"User-Agent": "IHSP-LinkTitle/1.0", "Accept": "text/html"}


async def _read_body(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= MAX_BYTES:
            break
    return b"".join(chunks)[:MAX_BYTES]


def _title_of(response: httpx.Response, body: bytes) -> str | None:
    content_type = response.headers.get("content-type", "")
    if response.status_code >= 400 or "html" not in content_type.lower():
        return None
    return parse_title(body.decode(response.encoding or "utf-8", "replace"))
