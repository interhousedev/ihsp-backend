"""SSRF-safe download of certificate PDFs from the issuer's site (uzbmb.uz).

Only https on ``uzbmb.uz`` or a subdomain is allowed. The mechanics (public-address
check, pinned connection, capped body) live in ``app.shared.safe_fetch``; this file
holds the issuer's policy: port 443, same-host redirects, 10 MiB, 20 s in total.
"""

from urllib.parse import unquote

from app.modules.certificates.domain.errors import (
    CertificateDownloadError,
    UnsafeCertificateUrlError,
)
from app.modules.certificates.ports.fetcher import FetchedFile
from app.shared.safe_fetch import (
    FetchPolicy,
    Resolver,
    SafeFetcher,
    host_or_subdomain_of,
    is_public,
    system_resolver,
)

import httpx

__all__ = ["SafeCertificateFetcher", "check_url", "is_public"]

ISSUER_DOMAIN = "uzbmb.uz"
MAX_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3


def _unsafe(details: str) -> Exception:
    return UnsafeCertificateUrlError(support_details=details)


def _failed(details: str) -> Exception:
    return CertificateDownloadError(support_details=details)


def issuer_policy(max_bytes: int = MAX_BYTES) -> FetchPolicy:
    """https/443 on the issuer's domain, same-host redirects, 20 s (5 s to connect)."""
    return FetchPolicy(
        schemes=frozenset({"https"}),
        ports=frozenset({443}),
        allowed_hosts=host_or_subdomain_of(ISSUER_DOMAIN),
        redirect_policy="same_host",
        mime_allow_list=None,
        max_bytes=max_bytes,
        total_timeout=20.0,
        connect_timeout=5.0,
        max_redirects=MAX_REDIRECTS,
        accept="application/pdf,*/*;q=0.5",
    )


def check_url(url: str) -> tuple[str, str]:
    """Return (host, path with query) of an allowed URL, or raise."""
    target = SafeFetcher(issuer_policy(), unsafe=_unsafe, failed=_failed).check(url)
    return target.host, target.path


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
        self._fetcher = SafeFetcher(
            issuer_policy(max_bytes),
            unsafe=_unsafe,
            failed=_failed,
            resolver=resolver,
            transport=transport,
        )

    async def fetch(self, url: str) -> FetchedFile:
        """Download the file; every hop is checked again."""
        body = await self._fetcher.fetch(url)
        return FetchedFile(name=_file_name(body.path), data=body.data)
