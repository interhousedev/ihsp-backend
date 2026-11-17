"""Exa contents (`POST {base_url}/contents`): the full text of known pages.

Admission's university chats read the top hits of a search in full. A failure is
logged and gives no texts: the hits' snippets still answer.
"""

from collections.abc import Sequence
from typing import Any

from app.modules.ai.infrastructure.exa import ExaApi, ExaCallError

import structlog

log = structlog.get_logger(__name__)

CONTENTS_PATH = "/contents"
MAX_URLS = 10
PAGE_CHARS = 8000


class ExaPageReader:
    """Reads page texts over an `ExaApi` aimed at `/contents` (or the fake)."""

    def __init__(self, client: ExaApi, *, max_characters: int) -> None:
        """Keep the client and the longest text asked for."""
        self.client = client
        self.max_characters = max_characters

    async def read(self, urls: Sequence[str]) -> dict[str, str]:
        """Return the text of each page Exa could read, by the URL asked for."""
        wanted = list(dict.fromkeys(urls))[:MAX_URLS]
        if not wanted:
            return {}
        body = {"urls": wanted, "text": {"maxCharacters": self.max_characters}}
        try:
            data = await self.client.search(body)
        except ExaCallError as error:
            log.warning("web_contents_failed", reason=str(error))
            return {}
        return texts_of(data.get("results"), wanted)


def texts_of(results: Any, wanted: list[str]) -> dict[str, str]:
    """The non-empty texts of an answer, keyed by the URL that was asked for."""
    found: dict[str, str] = {}
    if not isinstance(results, list):
        return found
    for item in results:
        if not isinstance(item, dict):
            continue
        url, text = item.get("url") or item.get("id"), item.get("text")
        if url in wanted and isinstance(text, str) and text.strip():
            found[url] = text.strip()
    return found
