"""Slide research and pictures for a confirmed presentation plan.

Per slide, concurrently (bounded by `NOTEBOOKS__SLIDES_RESEARCH_CONCURRENCY`): a web
search for background notes, then a search for freely licensed pictures. A picture
is downloaded (never hotlinked), checked for its type and size, stored in the files
module and kept with its author and license. Everything is best effort: a slide
without notes or pictures is still designed from the sources.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from app.modules.notebooks.domain.artifacts.slide_outline import PlanSlide
from app.modules.notebooks.domain.errors import SourceReadError
from app.modules.notebooks.ports.image_search import ImageCandidate, ImageSearch
from app.modules.notebooks.ports.web_materials import MaterialFetcher
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.contracts.web_search import (
    WebHit,
    WebSearchApi,
    WebSearchDisabledError,
    WebSearchQuotaError,
    WebSearchUnavailableError,
)

import structlog

log = structlog.get_logger(__name__)

STAGE_PLANNING: Final = "planning"
STAGE_RESEARCH: Final = "researching"
STAGE_IMAGES: Final = "images"
STAGE_DESIGN: Final = "designing"
HITS_PER_SLIDE: Final = 3
SNIPPET_CHARS: Final = 300
_ALT_CHARS: Final = 200
_EXTENSIONS: Final = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

OnStage = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class SlideResearch:
    """What the deck's model gets besides the sources."""

    notes: str = ""  # the `<research>` block, "" when nothing was found
    images: dict[str, dict[str, Any]] = field(default_factory=dict)  # "I1" -> image
    images_block: str = ""  # the `<images>` block, "" without pictures

    def task_suffix(self) -> str:
        """The text added to the task block."""
        parts = []
        if self.notes:
            parts.append(
                "Background notes from the web for each slide (use them to enrich "
                "the slides; they are not sources, never put them in `refs`):\n"
                f"<research>\n{self.notes}\n</research>"
            )
        if self.images_block:
            parts.append(
                "Pictures you may use (set `image_id` to a label):\n"
                f"<images>\n{self.images_block}\n</images>"
            )
        return "\n\n" + "\n\n".join(parts) if parts else ""


def image_kind(data: bytes) -> str | None:
    """The content type of PNG, JPEG and WebP bytes by their signature, else None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def attribution_text(candidate: ImageCandidate) -> str:
    """``Author, License`` (or just the license when the author is unknown)."""
    return ", ".join(part for part in (candidate.author, candidate.license) if part)


class SlidePipeline:
    """Researches the slides of a plan and gathers a picture or two for each."""

    def __init__(
        self,
        *,
        web_search: WebSearchApi | None,
        images: ImageSearch | None,
        fetcher: MaterialFetcher | None,
        files: FilesApi | None,
        settings: Settings,
    ) -> None:
        """Keep the ports; a missing one switches its step off."""
        self.web_search = web_search
        self.images = images
        self.fetcher = fetcher
        self.files = files
        self.cfg = settings.notebooks

    async def run(
        self,
        *,
        user_id: UUID,
        outline: list[PlanSlide],
        locale: str,
        on_stage: OnStage,
    ) -> SlideResearch:
        """Research, then pictures; `on_stage` is told which step starts."""
        gate = asyncio.Semaphore(self.cfg.slides_research_concurrency)
        notes = ""
        if self.cfg.slides_research_enabled and self.web_search is not None:
            await on_stage(STAGE_RESEARCH)
            notes = await self._research(user_id, outline, locale, gate)
        images: dict[str, dict[str, Any]] = {}
        block = ""
        if self._images_on():
            await on_stage(STAGE_IMAGES)
            images, block = await self._gather_images(user_id, outline, gate)
        await on_stage(STAGE_DESIGN)
        return SlideResearch(notes=notes, images=images, images_block=block)

    # - - - Research - - -

    async def _research(
        self,
        user_id: UUID,
        outline: list[PlanSlide],
        locale: str,
        gate: asyncio.Semaphore,
    ) -> str:
        """The notes of every slide, in slide order."""
        actor = Actor(user_id=user_id, roles=frozenset({Role.STUDENT}))
        found = await asyncio.gather(
            *(self._notes(actor, slide, locale, gate) for slide in outline)
        )
        lines = [
            f"Slide {number}. {slide.title}\n{text}"
            for number, (slide, text) in enumerate(zip(outline, found), start=1)
            if text
        ]
        return "\n\n".join(lines)

    async def _notes(
        self, actor: Actor, slide: PlanSlide, locale: str, gate: asyncio.Semaphore
    ) -> str:
        """Up to three hits of one slide as short lines; "" on any failure."""
        assert self.web_search is not None
        async with gate:
            try:
                outcome = await self.web_search.search(
                    actor, query=slide.title, locale=locale, kind="fast"
                )
            except (
                WebSearchDisabledError,
                WebSearchQuotaError,
                WebSearchUnavailableError,
            ):
                return ""
        hits: tuple[WebHit, ...] = tuple(outcome.hits[:HITS_PER_SLIDE])
        return "\n".join(
            f"- {hit.title}: {hit.snippet[:SNIPPET_CHARS]} ({hit.url})" for hit in hits
        )

    # - - - Pictures - - -

    def _images_on(self) -> bool:
        return (
            self.cfg.slides_images_per_slide > 0
            and self.cfg.slides_commons_enabled
            and self.images is not None
            and self.fetcher is not None
            and self.files is not None
        )

    async def _gather_images(
        self, user_id: UUID, outline: list[PlanSlide], gate: asyncio.Semaphore
    ) -> tuple[dict[str, dict[str, Any]], str]:
        """Stored pictures labelled I1..In, and the block that lists them."""
        per_slide = await asyncio.gather(
            *(self._slide_images(user_id, slide, gate) for slide in outline)
        )
        images: dict[str, dict[str, Any]] = {}
        lines: list[str] = []
        seen: set[str] = set()
        for number, (slide, stored) in enumerate(zip(outline, per_slide), start=1):
            for image in stored:
                if image["file_id"] in seen:
                    continue
                seen.add(image["file_id"])
                label = f"I{len(images) + 1}"
                images[label] = image
                lines.append(
                    f"{label} (for slide {number}, {slide.title}): {image['alt']}"
                )
        return images, "\n".join(lines)

    async def _slide_images(
        self, user_id: UUID, slide: PlanSlide, gate: asyncio.Semaphore
    ) -> list[dict[str, Any]]:
        """Download and store the pictures of one slide; skip every bad one."""
        assert self.images is not None
        async with gate:
            found = await self.images.search(
                slide.title, self.cfg.slides_images_per_slide
            )
            stored: list[dict[str, Any]] = []
            for candidate in found:
                image = await self._store(user_id, candidate)
                if image is not None:
                    stored.append(image)
        return stored

    async def _store(
        self, user_id: UUID, candidate: ImageCandidate
    ) -> dict[str, Any] | None:
        """One picture in the files module, or None when it is not usable."""
        assert self.fetcher is not None and self.files is not None
        limit = self.cfg.slides_image_max_bytes
        try:
            fetched = await self.fetcher.download(candidate.url, limit)
        except SourceReadError:
            return None
        kind = image_kind(fetched.data)
        if kind is None or len(fetched.data) > limit:
            return None
        name = f"{candidate.title[:80] or 'picture'}.{_EXTENSIONS[kind]}"
        try:
            ref = await self.files.store_bytes(
                owner_id=user_id,
                scope=FileScope.SYSTEM,
                purpose=FilePurpose.AI_UPLOAD,
                name=name,
                data=fetched.data,
            )
        except BaseError as exc:
            log.info("notebooks.slides.image_not_stored", code=exc.code)
            return None
        return {
            "file_id": str(ref.id),
            "alt": candidate.title[:_ALT_CHARS],
            "attribution": attribution_text(candidate),
            "source_url": candidate.source_url,
            "license": candidate.license,
        }
