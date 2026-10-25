"""Link validation rules: finding URLs in drafts and refusing unsafe targets."""

import ipaddress
import re
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from app.modules.lms.domain.authoring.errors import LinkCheckForbiddenTargetError

MAX_URLS: Final = 200
MAX_REDIRECTS: Final = 3
_URL: Final = re.compile(r"https?://[^\s<>\"'\\)\]]+", re.IGNORECASE)
_TRAILING: Final = ".,;:!?"

Resolver = Callable[[str, int], Awaitable[list[str]]]


@dataclass(frozen=True, slots=True)
class FoundLink:
    """A URL and the first step that contains it."""

    url: str
    step_id: str
    step_title: str


@dataclass(frozen=True, slots=True)
class LinkResult:
    """The outcome of checking one URL."""

    url: str
    status_code: int | None
    ok: bool
    error: str | None = None


def _strings(value: Any) -> Iterator[str]:
    """Yield every string in nested JSON-like data (keys excluded)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def urls_in(text: str) -> list[str]:
    """Return the http(s) URLs of a text, trailing punctuation removed."""
    return [match.rstrip(_TRAILING) for match in _URL.findall(text)]


def extract_links(
    steps: list[tuple[str, str, Any]], *, limit: int = MAX_URLS
) -> list[FoundLink]:
    """Return unique URLs of `(step_id, title, draft)` triples, at most `limit`."""
    found: dict[str, FoundLink] = {}
    for step_id, title, draft in steps:
        for text in _strings(draft):
            for url in urls_in(text):
                if url not in found and len(found) < limit:
                    found[url] = FoundLink(url, step_id, title)
    return list(found.values())


def is_public_address(address: str) -> bool:
    """Return True only for a globally routable unicast address."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


async def ensure_safe_url(url: str, resolve: Resolver) -> str:
    """Return the address to connect to, or raise LinkCheckForbiddenTargetError.

    Only http and https are allowed, and every address the host resolves to must
    be public.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host or parts.username:
        raise LinkCheckForbiddenTargetError(params={"reason": "scheme"})
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = [host] if _is_ip(host) else await resolve(host, port)
    except OSError as exc:
        raise LinkCheckForbiddenTargetError(params={"reason": "dns"}) from exc
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise LinkCheckForbiddenTargetError(params={"reason": "address"})
    return addresses[0]


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
