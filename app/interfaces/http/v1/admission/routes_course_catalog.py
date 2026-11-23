"""Courses-and-books catalogue and the books staff attach to a student."""

import datetime as dt
from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep, StudentCtx
from app.modules.admission.application.course_catalog import CatalogFilter
from app.modules.admission.domain.courses import (
    AttachedBook,
    CatalogEntry,
    CatalogKind,
    CatalogPage,
)

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class CatalogEntryOut(BaseModel):
    """A published LMS course or library book."""

    kind: CatalogKind
    id: str
    title: str
    summary: str = Field(description="Course summary or the book's authors.")
    cover_url: str | None
    url: str = Field(description="Absolute link to the LMS course or library page.")
    enrolled: bool = Field(description="Courses only: the caller takes it.")
    language: str | None = Field(description="Books only.")
    year: int | None = Field(description="Books only: year of publication.")
    pages: int | None = Field(description="Books only.")

    @classmethod
    def of(cls, e: CatalogEntry) -> "CatalogEntryOut":
        """Map a catalogue entry."""
        return cls(**{f: getattr(e, f) for f in cls.model_fields})


class CatalogPageOut(BaseModel):
    """One page of the catalogue."""

    items: list[CatalogEntryOut]
    has_more: bool

    @classmethod
    def of(cls, p: CatalogPage) -> "CatalogPageOut":
        """Map a page."""
        return cls(items=[CatalogEntryOut.of(i) for i in p.items], has_more=p.has_more)


class AttachedBookOut(BaseModel):
    """A book a staff member attached to a student."""

    book: CatalogEntryOut
    note: str | None
    attached_at: dt.datetime | None

    @classmethod
    def of(cls, entry: CatalogEntry, row: AttachedBook) -> "AttachedBookOut":
        """Map an entry and its attachment."""
        return cls(
            book=CatalogEntryOut.of(entry), note=row.note, attached_at=row.created_at
        )


class AttachedBookListOut(BaseModel):
    """The books attached to a student, newest first."""

    items: list[AttachedBookOut]


class AttachBookIn(BaseModel):
    """Attach a library book."""

    item_id: UUID
    note: str | None = Field(default=None, max_length=300)


async def browse_catalog(
    container: ContainerDep,
    ctx: AdmissionCtx,
    q: Annotated[str | None, Query(max_length=100)] = None,
    kind: CatalogFilter = "all",
    limit: Annotated[int, Query(ge=1, le=60)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogPageOut:
    """Every published LMS course and library book; search and filter by type."""
    page = await container.admission.course_catalog.browse(
        ctx, q, kind, limit=limit, offset=offset
    )
    return CatalogPageOut.of(page)


async def list_my_books(
    container: ContainerDep, ctx: StudentCtx
) -> AttachedBookListOut:
    """Books staff attached to the caller."""
    rows = await container.admission.course_catalog.books_of(ctx, ctx.user_id)
    return AttachedBookListOut(items=[AttachedBookOut.of(e, r) for e, r in rows])


async def list_student_books(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> AttachedBookListOut:
    """Books attached to a student (staff in scope or the student)."""
    rows = await container.admission.course_catalog.books_of(ctx, student_id)
    return AttachedBookListOut(items=[AttachedBookOut.of(e, r) for e, r in rows])


async def attach_book(
    student_id: UUID, body: AttachBookIn, container: ContainerDep, ctx: AdmissionCtx
) -> AttachedBookOut:
    """Attach a published library book to a student (staff only; idempotent)."""
    entry, row = await container.admission.course_catalog.attach(
        ctx, student_id, body.item_id, body.note
    )
    return AttachedBookOut.of(entry, row)


async def detach_book(
    student_id: UUID, item_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Remove an attached book (staff only)."""
    await container.admission.course_catalog.detach(ctx, student_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_R = router.add_api_route
_R(
    "/courses/catalog",
    browse_catalog,
    methods=["GET"],
    response_model=CatalogPageOut,
    operation_id="admission_course_catalog",
)
_R(
    "/courses/books",
    list_my_books,
    methods=["GET"],
    response_model=AttachedBookListOut,
    operation_id="admission_list_my_books",
)
_R(
    "/students/{student_id}/books",
    list_student_books,
    methods=["GET"],
    response_model=AttachedBookListOut,
    operation_id="admission_list_student_books",
)
_R(
    "/students/{student_id}/books",
    attach_book,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=AttachedBookOut,
    operation_id="admission_attach_book",
)
_R(
    "/students/{student_id}/books/{item_id}",
    detach_book,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admission_detach_book",
)
