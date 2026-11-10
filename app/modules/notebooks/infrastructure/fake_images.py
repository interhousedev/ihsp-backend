"""Deterministic image search and download for fake mode and tests (no network)."""

import base64
import re
from typing import Final

from app.modules.notebooks.ports.image_search import ImageCandidate
from app.modules.notebooks.ports.web_materials import (
    DownloadedMaterial,
    MaterialCandidate,
)

# A valid 1x1 PNG.
PNG_1X1: Final = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6k"
    "gAAAABJRU5ErkJggg=="
)
_SLUG: Final = re.compile(r"[^a-z0-9]+")


class FakeImageSearch:
    """Two free pictures per query, named after it."""

    async def search(self, query: str, limit: int) -> list[ImageCandidate]:
        """Up to `limit` candidates; the same query always gives the same ones."""
        slug = _SLUG.sub("-", query.casefold()).strip("-")[:40] or "picture"
        return [
            ImageCandidate(
                url=f"https://upload.wikimedia.org/fake/{slug}-{n}.png",
                title=f"{query[:80]} ({n})",
                author="Demo Author",
                license="CC BY-SA 4.0",
                source_url=f"https://commons.wikimedia.org/wiki/File:{slug}-{n}.png",
            )
            for n in range(1, min(limit, 2) + 1)
        ]


class FakeImageFetcher:
    """Serves the 1x1 PNG for any address (only `download` is used)."""

    async def candidates(self, page_url: str, limit: int) -> list[MaterialCandidate]:
        """A fake fetcher finds no linked files."""
        return []

    async def download(self, url: str, max_bytes: int) -> DownloadedMaterial:
        """The PNG."""
        return DownloadedMaterial(url=url, content_type="image/png", data=PNG_1X1)
