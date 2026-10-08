"""URL safety rules: scheme, credentials, length, blocklist, interstitial."""

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.modules.links.domain.errors import BlockedUrlError

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = ("http", "https")
INTERSTITIAL_ALLOWLIST = (
    "ihsu.uz",
    "docs.google.com",
    "drive.google.com",
    "youtube.com",
    "youtu.be",
    "wikipedia.org",
    "khanacademy.org",
    "stepik.org",
)


@dataclass(frozen=True, slots=True)
class CheckedUrl:
    """A URL that passed the policy."""

    url: str
    host: str


def host_matches(host: str, domains: Iterable[str]) -> bool:
    """True if the host is one of the domains or a subdomain of one."""
    return any(host == d or host.endswith("." + d) for d in domains)


def host_of(raw: str) -> str | None:
    """Return the lower-case host of a URL without a trailing dot, or None."""
    try:
        host = urlsplit(raw).hostname
    except ValueError:
        return None
    return host.rstrip(".").lower() if host else None


def is_public_ip(address: str) -> bool:
    """True if the IP address is globally routable (not private, loopback, ...)."""
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def _host_or_raise(url: str) -> str:
    """Validate scheme, host and credentials; return the lower-case host."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port  # raises ValueError for a malformed port
    except ValueError as error:
        raise BlockedUrlError(params={"reason": "malformed"}) from error
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedUrlError(params={"reason": "scheme"})
    if not host:
        raise BlockedUrlError(params={"reason": "host"})
    if parts.username is not None or parts.password is not None:
        raise BlockedUrlError(params={"reason": "credentials"})
    return host.rstrip(".").lower()


class UrlPolicy:
    """Validates URLs and decides which ones need an interstitial page."""

    def __init__(
        self,
        blocked_domains: frozenset[str],
        allowlist: tuple[str, ...] = INTERSTITIAL_ALLOWLIST,
    ) -> None:
        """Store the blocklist and the allowlist of trusted domains."""
        self.blocked_domains = blocked_domains
        self.allowlist = allowlist

    def check(self, raw: str) -> CheckedUrl:
        """Return the cleaned URL or raise BlockedUrlError."""
        url = raw.strip()
        if not url or len(url) > MAX_URL_LENGTH:
            raise BlockedUrlError(params={"reason": "length"})
        if any(ch.isspace() or ord(ch) < 32 for ch in url):
            raise BlockedUrlError(params={"reason": "characters"})
        host = _host_or_raise(url)
        if self.is_blocked(host):
            raise BlockedUrlError(params={"reason": "blocklist"})
        return CheckedUrl(url=url, host=host)

    def is_blocked(self, host: str) -> bool:
        """True if the host or a parent domain is on the blocklist."""
        return host_matches(host, self.blocked_domains)

    def is_blocked_url(self, raw: str) -> bool:
        """True if the URL's host is on the blocklist (checked again on open)."""
        host = host_of(raw)
        return host is not None and self.is_blocked(host)

    def needs_interstitial(self, raw: str) -> bool:
        """True unless the host is on the allowlist of trusted domains."""
        host = host_of(raw)
        return host is None or not host_matches(host, self.allowlist)
