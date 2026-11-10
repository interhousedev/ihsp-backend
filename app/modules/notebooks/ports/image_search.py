"""Port: license-safe pictures for slides (Wikimedia Commons)."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ImageCandidate:
    """A freely licensed picture found for a query, not yet downloaded."""

    url: str  # a direct https link to a jpeg / png / webp file
    title: str  # the file title, used as the alt text
    author: str  # plain text, "" when unknown
    license: str  # short name, e.g. "CC BY-SA 4.0" or "Public domain"
    source_url: str  # the page of the picture, for attribution


class ImageSearch(Protocol):
    """Finds pictures by a text query."""

    async def search(self, query: str, limit: int) -> list[ImageCandidate]:
        """Up to `limit` candidates; empty on any failure (never raises)."""
        ...
