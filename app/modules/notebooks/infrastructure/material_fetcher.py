"""Gathering the files of a web page with the SSRF-safe fetcher of URL sources."""

import asyncio

from app.modules.notebooks.domain.errors import SourceReadError
from app.modules.notebooks.infrastructure.material_links import extract_candidates
from app.modules.notebooks.infrastructure.web_fetcher import HttpWebFetcher, decode_body
from app.modules.notebooks.ports.web_materials import (
    DownloadedMaterial,
    MaterialCandidate,
)

import structlog

log = structlog.get_logger(__name__)

PAGE_TYPES = ("text/html",)
MATERIAL_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # many servers send office files so; sniffed later
    "image/png",
    "image/jpeg",
    "image/webp",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
)


class HttpMaterialFetcher:
    """Every hop is checked like a URL source: public addresses only, size, type."""

    def __init__(
        self,
        fetcher: HttpWebFetcher,
        *,
        min_image_px: int = 200,
        timeout_seconds: float = 15.0,
    ) -> None:
        """Store the fetcher and the scan limits."""
        self.fetcher = fetcher
        self.min_image_px = min_image_px
        self.timeout_seconds = timeout_seconds

    async def candidates(self, page_url: str, limit: int) -> list[MaterialCandidate]:
        """Read the page's markup again and scan it; any failure finds nothing."""
        try:
            page = await self.fetcher.download_raw(page_url, allowed=PAGE_TYPES)
        except SourceReadError:
            return []
        markup = decode_body(page.body, page.charset, html=True)
        return await asyncio.to_thread(
            extract_candidates,
            markup,
            page.url,
            limit=limit,
            min_image_px=self.min_image_px,
        )

    async def download(self, url: str, max_bytes: int) -> DownloadedMaterial:
        """The bytes of one candidate; `SourceReadError` on any refusal."""
        got = await self.fetcher.download_raw(
            url,
            allowed=MATERIAL_TYPES,
            max_bytes=max_bytes,
            timeout_seconds=self.timeout_seconds,
        )
        return DownloadedMaterial(got.url, got.content_type, got.body)
