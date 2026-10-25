"""Builds item cards: subject names, shelf state, progress, cover URL, tag."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.library.application.views import (
    BookCardView,
    ExternalCardView,
    ItemCardView,
    MaterialCardView,
    SubjectView,
    TagSource,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemKind, ShelfState
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilesApi

import structlog

log = structlog.get_logger(__name__)

EXCERPT_CHARS = 200
TAG_LABELS: dict[TagSource, str] = {
    "unilibrary": "UniLibrary",
    "book": "Library book",
    "material": "Material",
}
LOCALE_FALLBACK = ("uz", "ru", "en")


@dataclass(frozen=True, slots=True)
class Hit:
    """A full-text hit: the snippet and the page it was found on."""

    snippet: str
    page: int | None


def pick_name(names: Mapping[str, str], locale: str) -> str:
    """The name in the locale, falling back to uz, ru, en, then any."""
    for language in (locale, *LOCALE_FALLBACK):
        value = (names.get(language) or "").strip()
        if value:
            return value
    return next((v for v in names.values() if v), "")


def excerpt(text: str | None) -> str | None:
    """The first 200 characters, cut at a word, with an ellipsis."""
    if not text:
        return None
    clean = " ".join(text.split())
    if len(clean) <= EXCERPT_CHARS:
        return clean
    cut = clean[:EXCERPT_CHARS].rsplit(" ", 1)[0] or clean[:EXCERPT_CHARS]
    return f"{cut}…"


def tag_source(item: Item) -> TagSource:
    """The source tag of a card: UniLibrary, Library book or Material."""
    if item.kind is ItemKind.EXTERNAL:
        return "unilibrary"
    return "book" if item.kind is ItemKind.BOOK else "material"


class CardBuilder:
    """Turns items into `ItemCardView`s inside an open unit of work."""

    def __init__(
        self,
        *,
        academic: AcademicDirectory,
        files: FilesApi,
        cover_ttl_seconds: int,
    ) -> None:
        """Store the directories used to enrich cards."""
        self.academic = academic
        self.files = files
        self.cover_ttl_seconds = cover_ttl_seconds

    async def build(
        self,
        uow: LibraryUnitOfWork,
        items: Sequence[Item],
        *,
        viewer: Actor | None,
        locale: str,
        hits: Mapping[UUID, Hit] | None = None,
    ) -> list[ItemCardView]:
        """Cards for the items in the given order."""
        if not items:
            return []
        ids = [item.id for item in items]
        links = await uow.items.subject_links(ids)
        subject_ids = list({link.subject_id for ls in links.values() for link in ls})
        names = await self.academic.subject_names(subject_ids, locale)
        shelf = await uow.shelf.states(viewer.user_id, ids) if viewer else {}
        progress = await uow.progress.percents(viewer.user_id, ids) if viewer else {}
        cards: list[ItemCardView] = []
        for item in items:
            subjects = tuple(
                SubjectView(id=sid, name=names[sid])
                for sid in dict.fromkeys(
                    link.subject_id for link in links.get(item.id, [])
                )
                if sid in names
            )
            hit = (hits or {}).get(item.id)
            cards.append(
                await self._card(
                    item,
                    subjects=subjects,
                    shelf_state=shelf.get(item.id),
                    progress=progress.get(item.id),
                    locale=locale,
                    hit=hit,
                )
            )
        return cards

    async def _card(
        self,
        item: Item,
        *,
        subjects: tuple[SubjectView, ...],
        shelf_state: ShelfState | None,
        progress: float | None,
        locale: str,
        hit: Hit | None,
    ) -> ItemCardView:
        source = tag_source(item)
        external = None
        if item.external is not None:
            external = ExternalCardView(
                external_id=item.external.external_id,
                category=item.external.category,
                access=item.external.access,
                type_name=pick_name(item.external.type_name, locale),
                field_name=pick_name(item.external.field_name, locale),
                view_url=item.external.view_url,
                gone=item.external.gone_at is not None,
            )
        return ItemCardView(
            id=item.id,
            slug=item.slug,
            kind=item.kind,
            type=item.type,
            title=item.title,
            author_label=item.author_label,
            language=item.language.value,
            year_published=item.year_published,
            cover_url=await self.cover_url(item),
            description_excerpt=excerpt(item.description),
            subjects=subjects,
            years_of_study=tuple(item.years_of_study),
            has_text=item.has_text,
            page_count=item.page_count,
            shelf_state=shelf_state,
            progress_percent=progress if item.kind is not ItemKind.EXTERNAL else None,
            tag_source=source,
            tag_label=TAG_LABELS[source],
            snippet=hit.snippet if hit else None,
            snippet_page=hit.page if hit else None,
            material=(
                MaterialCardView(
                    uploader_name=item.material.uploader_name,
                    uploader_cohort=item.material.uploader_cohort,
                    uploader_role=item.material.uploader_role,
                )
                if item.material
                else None
            ),
            book=(
                BookCardView(
                    rights=item.book.rights,
                    licence=item.book.licence,
                    download_allowed=item.download_allowed,
                )
                if item.book
                else None
            ),
            external=external,
        )

    async def cover_url(self, item: Item) -> str | None:
        """A short-lived URL of the stored cover, or the hotlinked cover."""
        if item.cover_file_id is None:
            return item.cover_url
        try:
            return await self.files.download_url(
                item.cover_file_id, inline=True, ttl_seconds=self.cover_ttl_seconds
            )
        except BaseError:
            log.warning("library_cover_unavailable", item_id=str(item.id))
            return None
