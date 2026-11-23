"""One catalogue of every published LMS course and library book.

It also holds the books staff attach to a student.
"""

from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.courses import (
    AttachedBook,
    CatalogEntry,
    CatalogPage,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.courses import CourseSources
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.contracts.library import LibraryBookCard, LibraryBookCatalogue

CatalogFilter = Literal["all", "course", "book"]
LMS_LIMIT = 200
MAX_LIMIT = 60


class CourseCatalogService:
    """Browse courses and books; attach books to a student."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        sources: CourseSources,
        library: LibraryBookCatalogue | None,
        lms_url: str,
        library_url: str,
    ) -> None:
        """Keep the collaborators; `library` is None where the library is off."""
        self._uow = uow_factory
        self._access = access
        self._sources = sources
        self._library = library
        self._lms = lms_url.rstrip("/")
        self._lib = library_url.rstrip("/")

    def book_url(self, item_id: UUID) -> str:
        """The library page of a book."""
        return f"{self._lib}/item/?{urlencode({'id': str(item_id)})}"

    def entry_of_book(self, card: LibraryBookCard) -> CatalogEntry:
        """A catalogue entry for a book."""
        return CatalogEntry(
            kind="book",
            id=str(card.id),
            title=card.title,
            summary=card.author_label,
            cover_url=card.cover_url,
            url=self.book_url(card.id),
            language=card.language,
            year=card.year_published,
            pages=card.page_count,
        )

    async def browse(
        self,
        ctx: AdmissionContext,
        query: str | None,
        kind: CatalogFilter,
        *,
        limit: int,
        offset: int,
    ) -> CatalogPage:
        """Courses first, then books; `offset` runs over the joined list."""
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)
        q = (query or "").strip() or None
        courses = (
            await self._sources.lms_find(ctx.actor, q, LMS_LIMIT)
            if kind in ("all", "course")
            else []
        )
        items = [
            CatalogEntry(
                kind="course",
                id=c.id,
                title=c.title,
                summary=c.summary,
                cover_url=c.cover_url,
                url=f"{self._lms}/course/{c.id}/",
                enrolled=c.enrolled,
            )
            for c in courses[offset : offset + limit]
        ]
        more = offset + limit < len(courses)
        if kind in ("all", "book") and self._library is not None:
            room = limit - len(items)
            page = await self._library.search_books(
                ctx.actor,
                q,
                limit=max(room, 1),
                offset=max(0, offset - len(courses)),
            )
            items += [self.entry_of_book(b) for b in page.items[:room]]
            more = more or page.has_more or len(page.items) > room
        return CatalogPage(items=items, has_more=more)

    async def books_of(
        self, ctx: AdmissionContext, student_id: UUID
    ) -> list[tuple[CatalogEntry, AttachedBook]]:
        """The student's attached books that the caller may still see."""
        await self._access.require(
            ctx, student_id, Permission.PROFILE_READ, object_type="attached_books"
        )
        if self._library is None:
            return []
        async with self._uow() as uow:
            rows = await uow.attached_books.list_for(student_id)
        cards = {
            c.id: c
            for c in await self._library.books_by_ids(
                ctx.actor, [r.item_id for r in rows]
            )
        }
        return [
            (self.entry_of_book(cards[r.item_id]), r)
            for r in rows
            if r.item_id in cards
        ]

    async def _staff(self, ctx: AdmissionContext, student_id: UUID) -> None:
        resolution = await self._access.require(
            ctx, student_id, Permission.PROFILE_COMMENT, object_type="attached_books"
        )
        if resolution.owner:
            raise AdmissionForbiddenError(params={"permission": "books:attach"})

    async def attach(
        self,
        ctx: AdmissionContext,
        student_id: UUID,
        item_id: UUID,
        note: str | None,
    ) -> tuple[CatalogEntry, AttachedBook]:
        """Attach a published book to the student (idempotent)."""
        await self._staff(ctx, student_id)
        if self._library is None:
            raise AdmissionNotFoundError()
        found = await self._library.books_by_ids(ctx.actor, [item_id])
        if not found:
            raise AdmissionNotFoundError()
        async with self._uow() as uow:
            row = await uow.attached_books.add(
                AttachedBook(
                    student_id=student_id,
                    item_id=item_id,
                    attached_by=ctx.user_id,
                    note=(note or "").strip() or None,
                )
            )
            uow.access.audit(
                AuditEvent(
                    action="book.attached",
                    actor_id=ctx.user_id,
                    student_id=student_id,
                    object_type="library_item",
                    object_id=item_id,
                )
            )
            await uow.commit()
        return self.entry_of_book(found[0]), row

    async def detach(
        self, ctx: AdmissionContext, student_id: UUID, item_id: UUID
    ) -> None:
        """Remove an attachment."""
        await self._staff(ctx, student_id)
        async with self._uow() as uow:
            if not await uow.attached_books.remove(student_id, item_id):
                raise AdmissionNotFoundError()
            uow.access.audit(
                AuditEvent(
                    action="book.detached",
                    actor_id=ctx.user_id,
                    student_id=student_id,
                    object_type="library_item",
                    object_id=item_id,
                )
            )
            await uow.commit()
