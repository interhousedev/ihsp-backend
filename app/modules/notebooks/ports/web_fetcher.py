"""Port: fetching a web page for URL sources (phase 2, SSRF-safe)."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """The main text of a page or PDF."""

    url: str  # after redirects
    title: str | None
    text: str
    content_type: str  # text/html | text/plain | application/pdf
    pages: tuple[int, ...] = ()  # character offset of each PDF page


class WebFetcher(Protocol):
    """Downloads a public page and extracts its text."""

    async def fetch(self, url: str) -> FetchedPage:
        """Fetch a page; raise `SourceReadError` with a failure code on any problem.

        Codes: forbidden, fetch_failed, unsupported_type, too_large.
        """
        ...
