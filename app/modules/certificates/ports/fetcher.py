"""Port: download of a certificate PDF from the issuer's site."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FetchedFile:
    """A downloaded file."""

    name: str
    data: bytes


class CertificateFetcher(Protocol):
    """Fetches a PDF by URL; raises ``CertificateDownloadError`` when it cannot."""

    async def fetch(self, url: str) -> FetchedFile:
        """Return the file at an issuer URL (https, issuer domain, size capped)."""
        ...
