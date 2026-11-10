"""Wikimedia Commons image search: freely licensed pictures with their authors."""

import html
import re
from typing import Any, Final

from app.modules.notebooks.ports.image_search import ImageCandidate

import httpx
import structlog

log = structlog.get_logger(__name__)

API_URL: Final = "https://commons.wikimedia.org/w/api.php"
USER_AGENT: Final = "IHSP-Notebooks/1.0 (+https://ihsu.uz) httpx"
IMAGE_MIMES: Final = frozenset({"image/jpeg", "image/png", "image/webp"})
MIN_WIDTH: Final = 600
_TAGS: Final = re.compile(r"<[^>]+>")
_FREE: Final = ("cc by", "cc0", "public domain", "pd", "cc-by", "cc-zero")


def _plain(value: Any) -> str:
    """HTML metadata as one line of plain text."""
    return " ".join(html.unescape(_TAGS.sub(" ", str(value or ""))).split())


def is_free_license(name: str) -> bool:
    """CC BY, CC BY-SA, CC0 and the public domain; not "fair use" or NC/ND."""
    low = name.casefold()
    if not low or "nc" in low.split() or "-nc" in low or "-nd" in low:
        return False
    return low.startswith(_FREE)


def parse_candidates(payload: dict[str, Any], limit: int) -> list[ImageCandidate]:
    """The usable candidates of a Commons `query` answer, best match first."""
    pages = (payload.get("query") or {}).get("pages") or {}
    ordered = sorted(pages.values(), key=lambda p: int(p.get("index") or 0))
    found: list[ImageCandidate] = []
    for page in ordered:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        mime = str(info.get("mime") or "")
        license_name = _plain((meta.get("LicenseShortName") or {}).get("value"))
        url = str(info.get("thumburl") or info.get("url") or "")
        if (
            mime not in IMAGE_MIMES
            or not url.startswith("https://")
            or int(info.get("width") or 0) < MIN_WIDTH
            or not is_free_license(license_name)
        ):
            continue
        title = _plain(page.get("title")).removeprefix("File:")
        found.append(
            ImageCandidate(
                url=url,
                title=title.rsplit(".", 1)[0][:200],
                author=_plain((meta.get("Artist") or {}).get("value"))[:200],
                license=license_name[:60],
                source_url=str(info.get("descriptionurl") or "")[:500],
            )
        )
        if len(found) >= limit:
            break
    return found


class CommonsImageSearch:
    """`ImageSearch` over the public Wikimedia Commons API."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        """Keep the per-request timeout."""
        self._timeout = timeout

    async def search(self, query: str, limit: int) -> list[ImageCandidate]:
        """Up to `limit` free pictures; empty when the service fails."""
        if not query.strip() or limit <= 0:
            return []
        params = {
            "action": "query",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrlimit": str(min(limit * 4, 20)),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime|size",
            "iiurlwidth": "1280",
            "format": "json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers={"User-Agent": USER_AGENT}
            ) as client:
                response = await client.get(API_URL, params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("notebooks.commons.failed", error=type(exc).__name__)
            return []
        return parse_candidates(payload, limit)
