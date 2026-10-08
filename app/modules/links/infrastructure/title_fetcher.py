"""Fetching the <title> of a page without letting users reach internal hosts."""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
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
        except (httpx.HTTPError, OSError, ValueError):
            log.info("title_fetch_failed", host=fallback)
            return fallback
        return title or fallback

    async def _title(self, url: str) -> str | None:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=self.transport
        ) as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                if not await self._allowed(current):
                    return None
                async with client.stream("GET", current, headers=_HEADERS) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            return None
                        current = urljoin(current, location)
                        continue
                    return await _read_title(response)
        return None

    async def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.hostname
        if parts.scheme not in ("http", "https") or not host:
            return False
        if parts.port not in FETCH_PORTS:
            return False
        if _is_ip_literal(host):
            return is_public_ip(host)
        addresses = await self.resolver(host)
        return bool(addresses) and all(is_public_ip(a) for a in addresses)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


_HEADERS = {"User-Agent": "IHSP-LinkTitle/1.0", "Accept": "text/html"}


async def _read_title(response: httpx.Response) -> str | None:
    content_type = response.headers.get("content-type", "")
    if response.status_code >= 400 or "html" not in content_type.lower():
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= MAX_BYTES:
            break
    markup = b"".join(chunks)[:MAX_BYTES].decode(
        response.encoding or "utf-8", "replace"
    )
    return parse_title(markup)
