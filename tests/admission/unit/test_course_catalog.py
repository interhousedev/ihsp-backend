"""The courses-and-books catalogue and the books staff attach to a student."""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from app.modules.admission.application.course_catalog import CourseCatalogService
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.admission_assistant import CourseHit
from app.shared.contracts.library import LibraryBookCard, LibraryBookPage
from tests.admission.unit.fakes import FakeStore, FakeUow

import pytest

STAFF = uuid4()
STUDENT = uuid4()


def card(title: str) -> LibraryBookCard:
    return LibraryBookCard(
        uuid4(), title.lower(), title, "A. Author", None, "en", 2020, 90
    )


class Library:
    def __init__(self, books: list[LibraryBookCard]) -> None:
        self.books = books

    async def search_books(
        self, actor: Actor, query: str | None, *, limit: int, offset: int
    ) -> LibraryBookPage:
        found = [b for b in self.books if (query or "").lower() in b.title.lower()]
        return LibraryBookPage(
            items=found[offset : offset + limit], has_more=len(found) > offset + limit
        )

    async def books_by_ids(
        self, actor: Actor, item_ids: Sequence[UUID]
    ) -> list[LibraryBookCard]:
        by_id = {b.id: b for b in self.books}
        return [by_id[i] for i in item_ids if i in by_id]


class Sources:
    def __init__(self, hits: list[CourseHit]) -> None:
        self.hits = hits

    async def lms_find(
        self, actor: Actor, query: str | None, limit: int
    ) -> list[CourseHit]:
        return [h for h in self.hits if (query or "").lower() in h.title.lower()][
            :limit
        ]


class Access:
    """Resolves the caller as the student (`owner`) or as staff."""

    async def require(
        self, ctx: Any, student_id: UUID, permission: Any, **kw: Any
    ) -> Any:
        return SimpleNamespace(owner=ctx.user_id == student_id)


def ctx(user: UUID) -> Any:
    return SimpleNamespace(
        user_id=user, actor=Actor(user_id=user, roles=frozenset({Role.COUNSELOR}))
    )


def hit(title: str) -> CourseHit:
    return CourseHit(str(uuid4()), title, "summary", "/x", False, "https://c/cover.png")


def build(
    books: list[LibraryBookCard], hits: list[CourseHit]
) -> tuple[CourseCatalogService, FakeStore]:
    store = FakeStore()
    svc = CourseCatalogService(
        lambda: FakeUow(store),  # type: ignore[arg-type,return-value]
        Access(),  # type: ignore[arg-type]
        Sources(hits),  # type: ignore[arg-type]
        Library(books),
        "https://lms.test/",
        "https://lib.test",
    )
    return svc, store


async def test_browse_lists_courses_then_books_with_links_and_filter() -> None:
    """Both kinds appear with covers and links; the filter narrows to one."""
    course = hit("Algebra")
    svc, _ = build([card("Algebra book"), card("History")], [course])
    page = await svc.browse(ctx(STAFF), "alg", "all", limit=10, offset=0)
    assert [(e.kind, e.title) for e in page.items] == [
        ("course", "Algebra"),
        ("book", "Algebra book"),
    ]
    assert page.items[0].url == f"https://lms.test/course/{course.id}/"
    assert page.items[0].cover_url == "https://c/cover.png"
    assert page.items[1].url.startswith("https://lib.test/item/?id=")
    only_books = await svc.browse(ctx(STAFF), None, "book", limit=10, offset=0)
    assert {e.kind for e in only_books.items} == {"book"}
    only_courses = await svc.browse(ctx(STAFF), None, "course", limit=10, offset=0)
    assert [e.kind for e in only_courses.items] == ["course"]


async def test_browse_pages_over_the_joined_list() -> None:
    """Offset runs across courses and then books without gaps or repeats."""
    svc, _ = build([card(f"B{i}") for i in range(3)], [hit("C0"), hit("C1")])
    seen: list[str] = []
    offset = 0
    while True:
        page = await svc.browse(ctx(STAFF), None, "all", limit=2, offset=offset)
        seen += [e.title for e in page.items]
        offset += 2
        if not page.has_more:
            break
    assert seen == ["C0", "C1", "B0", "B1", "B2"]


async def test_staff_attaches_lists_and_detaches_a_book() -> None:
    """Attach is idempotent; the student reads it; detach removes it."""
    book = card("Physics")
    svc, store = build([book], [])
    first = await svc.attach(ctx(STAFF), STUDENT, book.id, "  start here ")
    again = await svc.attach(ctx(STAFF), STUDENT, book.id, None)
    assert first[1].id == again[1].id and first[1].note == "start here"
    mine = await svc.books_of(ctx(STUDENT), STUDENT)
    assert [e.title for e, _ in mine] == ["Physics"]
    assert [a.action for a in store.audit].count("book.attached") == 2
    await svc.detach(ctx(STAFF), STUDENT, book.id)
    assert await svc.books_of(ctx(STUDENT), STUDENT) == []
    with pytest.raises(AdmissionNotFoundError):
        await svc.detach(ctx(STAFF), STUDENT, book.id)


async def test_student_cannot_attach_and_unknown_book_is_not_found() -> None:
    """Only staff attach; a book the library does not list is a 404."""
    book = card("Chemistry")
    svc, _ = build([book], [])
    with pytest.raises(AdmissionForbiddenError):
        await svc.attach(ctx(STUDENT), STUDENT, book.id, None)
    with pytest.raises(AdmissionNotFoundError):
        await svc.attach(ctx(STAFF), STUDENT, uuid4(), None)
