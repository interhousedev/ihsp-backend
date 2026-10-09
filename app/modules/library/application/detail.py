"""Builds `ItemDetail` (the TS contract): the card plus status, files, topics, lists."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.access import (
    can_add_to_notebook,
    can_download,
    can_read_content,
    is_librarian,
    is_owner,
    is_signed_in,
)
from app.modules.library.domain.entities import Item, ItemFile
from app.modules.library.domain.enums import (
    FileFormat,
    Importance,
    ItemKind,
    ItemStatus,
    TextStatus,
    Visibility,
)
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.i18n.core import I18nCore


@dataclass(frozen=True, slots=True)
class ItemFileView:
    """`ItemFile` of the TS contract; `id` is the file id of the files module."""

    id: UUID
    format: FileFormat
    is_primary: bool
    pages: int | None
    byte_size: int
    readable: bool
    text_status: TextStatus
    toc: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class TopicRefView:
    """A topic the item feeds, with the page range."""

    id: UUID
    name: str
    page_from: int | None
    page_to: int | None


@dataclass(frozen=True, slots=True)
class ListRefView:
    """A reading list the item is on."""

    id: UUID
    title: str
    importance: Importance


@dataclass(frozen=True, slots=True)
class RightsBoxView:
    """The rights statement shown on a book page."""

    text: str
    attribution: str | None
    download_allowed: bool


@dataclass(frozen=True, slots=True)
class CanView:
    """What the caller may do with the item (the buttons the UI draws)."""

    read: bool
    download: bool
    add_to_notebook: bool
    report: bool
    edit: bool


@dataclass(frozen=True, slots=True)
class ProgressView:
    """Where the viewer stopped in the item (books and materials only)."""

    file_id: UUID
    locator: dict[str, Any]
    percent: float


@dataclass(frozen=True, slots=True)
class ItemDetailView:
    """`ItemDetail` of the TS contract."""

    card: ItemCardView
    status: ItemStatus
    status_reason: str | None
    status_note: str | None
    visibility: Visibility
    subtitle: str | None
    description: str | None
    publisher: str | None
    isbn: str | None
    files: tuple[ItemFileView, ...]
    topics: tuple[TopicRefView, ...]
    lists: tuple[ListRefView, ...]
    can: CanView
    rights_box: RightsBoxView | None = None
    external_keywords: tuple[str, ...] | None = None
    external_isbn: str | None = None
    progress: ProgressView | None = None


def file_view(item_file: ItemFile) -> ItemFileView:
    """Map a stored file to its view."""
    return ItemFileView(
        id=item_file.file_id,
        format=item_file.format,
        is_primary=item_file.is_primary,
        pages=item_file.pages,
        byte_size=item_file.byte_size,
        readable=item_file.readable,
        text_status=item_file.text_status,
        toc=tuple(item_file.toc),
    )


def can_edit(item: Item, actor: Actor | None) -> bool:
    """The owner of an item, and librarians for any book or material."""
    if item.kind is ItemKind.EXTERNAL:
        return is_librarian(actor)
    return is_owner(item, actor) or is_librarian(actor)


class DetailBuilder:
    """Turns an item into `ItemDetailView` inside an open unit of work."""

    def __init__(
        self, *, cards: CardBuilder, i18n: I18nCore, academic: AcademicDirectory
    ) -> None:
        """Store the card builder, the translations and the academic directory."""
        self.cards = cards
        self.i18n = i18n
        self.academic = academic

    async def build(
        self,
        uow: LibraryUnitOfWork,
        item: Item,
        *,
        viewer: Actor | None,
        locale: str,
        anonymous_cards: bool = False,
    ) -> ItemDetailView:
        """The detail of one item as `viewer` may see it."""
        (card,) = await self.cards.build(uow, [item], viewer=viewer, locale=locale)
        topic_links = (await uow.items.topic_links([item.id])).get(item.id, [])
        names = await uow.taxonomy.topic_names([link.topic_id for link in topic_links])
        group_id = None
        if viewer is not None and Role.STUDENT in viewer.roles:
            group_id = await self.academic.student_group_id(viewer.user_id)
        lists = await uow.lists.lists_for_item(
            item.id, group_id=group_id, staff=is_librarian(viewer)
        )
        saved = (
            await uow.progress.get(viewer.user_id, item.id)
            if viewer is not None and item.kind is not ItemKind.EXTERNAL
            else None
        )
        external = item.external
        snapshot = external.snapshot if external else {}
        keywords = snapshot.get("keywords")
        return ItemDetailView(
            card=card,
            status=item.status,
            status_reason=item.status_reason,
            status_note=item.status_note,
            visibility=item.visibility,
            subtitle=item.subtitle,
            description=item.description,
            publisher=item.publisher,
            isbn=item.isbn,
            files=tuple(file_view(f) for f in item.files),
            topics=tuple(
                TopicRefView(
                    id=link.topic_id,
                    name=_topic_name(names.get(link.topic_id, {}), locale),
                    page_from=link.page_from,
                    page_to=link.page_to,
                )
                for link in topic_links
                if link.topic_id in names
            ),
            lists=tuple(ListRefView(id=i, title=t, importance=m) for i, t, m in lists),
            can=CanView(
                read=can_read_content(item, viewer, anonymous_cards=anonymous_cards),
                download=can_download(item, viewer, anonymous_cards=anonymous_cards),
                add_to_notebook=can_add_to_notebook(item, viewer),
                report=is_signed_in(viewer) and item.status is ItemStatus.PUBLISHED,
                edit=can_edit(item, viewer),
            ),
            rights_box=self._rights_box(item, locale),
            external_keywords=(
                tuple(str(k) for k in keywords) if isinstance(keywords, list) else None
            ),
            external_isbn=(str(snapshot["isbn"]) if snapshot.get("isbn") else None),
            progress=(
                ProgressView(
                    file_id=saved.file_id,
                    locator=dict(saved.locator),
                    percent=saved.percent,
                )
                if saved
                else None
            ),
        )

    def _rights_box(self, item: Item, locale: str) -> RightsBoxView | None:
        if item.book is None:
            return None
        text = self.i18n.t(locale, f"library-rights-{item.book.rights.value}")
        attribution = item.book.rights_basis.get("attribution")
        return RightsBoxView(
            text=text,
            attribution=str(attribution) if attribution else None,
            download_allowed=item.download_allowed,
        )


def _topic_name(names: dict[str, str], locale: str) -> str:
    for language in (locale, "uz", "ru", "en"):
        value = (names.get(language) or "").strip()
        if value:
            return value
    return ""
