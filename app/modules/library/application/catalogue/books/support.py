"""What the book use cases share: reference checks, checklist facts, the detail."""

from collections.abc import Mapping, Sequence
from datetime import date
from uuid import UUID

from app.modules.library.application.catalogue.common import anonymous_cards
from app.modules.library.application.detail import DetailBuilder, ItemDetailView
from app.modules.library.application.locale import resolve_locale
from app.modules.library.domain.catalogue_books import BookData
from app.modules.library.domain.catalogue_errors import InvalidReferenceError
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import FileFormat, ItemKind
from app.modules.library.domain.errors import ItemNotFoundError
from app.modules.library.domain.rights import ChecklistFacts
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory


class BookSupport:
    """Collaborators of the book use cases (one instance, built in the wiring)."""

    def __init__(
        self,
        *,
        academic: AcademicDirectory,
        files: FilesApi,
        detail: DetailBuilder,
        identity: IdentityDirectory,
        clock: Clock,
        settings: LibrarySettings,
    ) -> None:
        """Store the collaborators."""
        self.academic = academic
        self.files = files
        self.detail = detail
        self.identity = identity
        self.clock = clock
        self.settings = settings

    def today(self) -> date:
        """The date the rights rules are checked against."""
        return self.clock.now().date()

    async def get_book(
        self, uow: LibraryUnitOfWork, book_id: UUID, *, lock: bool = False
    ) -> Item:
        """A stored book in any status; anything else is `library/not-found`."""
        item = await uow.items.get(book_id, lock=lock)
        if item is None or item.kind is not ItemKind.BOOK:
            raise ItemNotFoundError(support_details=f"no book {book_id}")
        return item

    async def validate_refs(
        self,
        uow: LibraryUnitOfWork,
        actor: Actor,
        data: BookData,
        *,
        previous: BookData | None = None,
    ) -> None:
        """Subjects, topics and files named in the form must exist (and be usable)."""
        subject_ids = list({link.subject_id for link in data.subjects})
        known = await self.academic.subject_names(subject_ids, "uz")
        _require_all("subjects", subject_ids, known)
        topic_ids = list({link.topic_id for link in data.topics})
        topics = await uow.taxonomy.topic_names(topic_ids)
        _require_all("topics", topic_ids, topics)
        for field, file_id, old in (
            ("cover_file_id", data.cover_file_id, previous and previous.cover_file_id),
            (
                "rights_proof_file_id",
                data.rights_proof_file_id,
                previous and previous.rights_proof_file_id,
            ),
        ):
            if file_id is not None and file_id != old:
                await self._require_usable_file(field, file_id, actor)

    async def _require_usable_file(
        self, field: str, file_id: UUID, actor: Actor
    ) -> None:
        ref = await self.files.get(file_id)
        if ref is None or not await self.files.check_access(file_id, actor):
            raise InvalidReferenceError(
                params={"field": field}, support_details=f"{field} {file_id} unusable"
            )

    async def facts(self, uow: LibraryUnitOfWork, item: Item) -> ChecklistFacts:
        """What the publish checklist looks at, read from the stored book."""
        details = item.book
        if details is None:
            raise ValueError(f"item {item.id} is not a book")
        links = (await uow.items.subject_links([item.id])).get(item.id, [])
        collections = await uow.items.collection_ids(item.id)
        primary = item.primary_file
        return ChecklistFacts(
            rights=details.rights,
            rights_basis=details.rights_basis,
            licence=details.licence,
            proof_file_id=details.rights_proof_file_id,
            primary_text_status=primary.text_status if primary else None,
            primary_is_pdf=bool(primary and primary.format is FileFormat.PDF),
            has_cover=bool(item.cover_file_id or item.cover_url),
            subject_count=len({link.subject_id for link in links}),
            collection_count=len(collections),
        )

    async def detail_view(
        self,
        uow: LibraryUnitOfWork,
        item: Item,
        actor: Actor,
        accept_language: str | None,
    ) -> ItemDetailView:
        """The detail of the book as the librarian sees it."""
        locale = await resolve_locale(self.identity, actor, accept_language)
        return await self.detail.build(
            uow,
            item,
            viewer=actor,
            locale=locale,
            anonymous_cards=anonymous_cards(self.settings),
        )


def _require_all(
    field: str, wanted: Sequence[UUID], known: Mapping[UUID, object]
) -> None:
    missing = [str(x) for x in wanted if x not in known]
    if missing:
        raise InvalidReferenceError(
            params={"field": field, "ids": missing},
            support_details=f"unknown {field}: {missing}",
        )
