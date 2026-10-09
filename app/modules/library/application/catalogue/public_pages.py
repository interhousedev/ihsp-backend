"""Data for the server-rendered public pages `/b/{slug}` and `/sitemap.xml` (§ 3.13)."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.library.application.cards import CardBuilder, pick_name
from app.modules.library.application.catalogue.common import anonymous_cards
from app.modules.library.application.locale import resolve_locale
from app.modules.library.domain.access import can_view
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    ItemKind,
    ItemLanguage,
    ItemStatus,
    ItemType,
    Visibility,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.settings import LibrarySettings
from app.shared.contracts.identity import IdentityDirectory
from app.shared.i18n.core import I18nCore

SITEMAP_LIMIT = 50_000


@dataclass(frozen=True, slots=True)
class PublicItemPage:
    """What the page shows; nothing here is secret for a lyceum-only item."""

    locale: str
    kind: ItemKind
    type: ItemType
    title: str
    subtitle: str | None
    authors: list[str]
    description: str | None
    cover_url: str | None
    language: ItemLanguage
    year_published: int | None
    publisher: str | None
    isbn: str | None
    rights_text: str | None
    attribution: str | None
    licence: str | None
    uploader: str | None
    external_url: str | None
    canonical_url: str
    app_url: str
    indexable: bool
    sign_in_required: bool
    tag_label: str


@dataclass(frozen=True, slots=True)
class SitemapEntry:
    """One URL of the sitemap."""

    url: str
    changed: datetime


class GetPublicItemPage:
    """The page of one published book, material or visible UniLibrary card."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        cards: CardBuilder,
        identity: IdentityDirectory,
        i18n: I18nCore,
        settings: LibrarySettings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.cards = cards
        self.identity = identity
        self.i18n = i18n
        self.settings = settings

    async def execute(
        self, slug: str, *, accept_language: str | None = None
    ) -> PublicItemPage | None:
        """The page, or None for anything unknown or not shown (never say why)."""
        locale = await resolve_locale(self.identity, None, accept_language)
        async with self.uow_factory() as uow:
            item = await uow.items.get_by_slug(slug)
            if item is None or not self._shown(item):
                return None
            cover = await self.cards.cover_url(item)
        return self._page(item, locale, cover)

    def _shown(self, item: Item) -> bool:
        if (
            item.status is not ItemStatus.PUBLISHED
            or item.visibility is Visibility.HIDDEN
        ):
            return False
        if item.kind is ItemKind.EXTERNAL:
            return can_view(item, None, anonymous_cards=anonymous_cards(self.settings))
        return True

    def _page(self, item: Item, locale: str, cover: str | None) -> PublicItemPage:
        base = self.settings.public_base_url.rstrip("/")
        public = item.visibility is Visibility.PUBLIC
        return PublicItemPage(
            locale=locale,
            kind=item.kind,
            type=item.type,
            title=item.title,
            subtitle=item.subtitle,
            authors=list(item.authors)
            or ([item.author_label] if item.author_label else []),
            description=item.description,
            cover_url=cover,
            language=item.language,
            year_published=item.year_published,
            publisher=item.publisher,
            isbn=item.isbn,
            rights_text=self._rights_text(item, locale),
            attribution=_attribution(item),
            licence=item.book.licence if item.book else None,
            uploader=_uploader(item) if public else None,
            external_url=item.external.view_url if item.external else None,
            canonical_url=f"{base}/b/{item.slug}",
            app_url=f"{base}/item/?id={item.slug}",
            indexable=public,
            sign_in_required=not public,
            tag_label=_tag(item, locale),
        )

    def _rights_text(self, item: Item, locale: str) -> str | None:
        if item.book is None:
            return None
        return self.i18n.t(locale, f"library-rights-{item.book.rights.value}")


class ListSitemap:
    """URLs of the public published books and materials."""

    def __init__(self, *, uow_factory: UowFactory, settings: LibrarySettings) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.settings = settings

    async def execute(self) -> list[SitemapEntry]:
        """One entry per public item, most recently changed first."""
        base = self.settings.public_base_url.rstrip("/")
        async with self.uow_factory() as uow:
            rows = await uow.items.sitemap_entries(limit=SITEMAP_LIMIT)
        return [SitemapEntry(f"{base}/b/{slug}", changed) for slug, changed in rows]


def _attribution(item: Item) -> str | None:
    if item.book is None:
        return None
    value = item.book.rights_basis.get("attribution")
    return str(value) if value else None


def _uploader(item: Item) -> str | None:
    material = item.material
    if material is None:
        return None
    cohort = f", {material.uploader_cohort}" if material.uploader_cohort else ""
    return f"{material.uploader_name}{cohort}"


def _tag(item: Item, locale: str) -> str:
    if item.external is not None:
        return pick_name(item.external.type_name, locale) or "UniLibrary"
    return "Library book" if item.kind is ItemKind.BOOK else "Material"
