"""LIB-3 (files part): the library scope on real PostgreSQL."""

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.infrastructure.uow import SqlFilesUnitOfWork
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from tests.fakes.clock import FixedClock
from tests.files.integration.test_file_repository import make_file

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def uow(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> AsyncIterator[SqlFilesUnitOfWork]:
    """A unit of work inside the test's outer transaction (rolled back after)."""
    work = SqlFilesUnitOfWork(sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer)
    async with work:
        yield work


def library_file(clock: FixedClock, **fields: object) -> StoredFile:
    """A ready library book."""
    values: dict[str, object] = {
        "scope": FileScope.LIBRARY,
        "purpose": FilePurpose.LIBRARY_BOOK,
        "name": "book.pdf",
        "content_type": "application/pdf",
        "byte_size": 100,
    }
    values.update(fields)
    file = make_file(clock, **values)
    file.key = f"library/2026-10/{file.id}.pdf"
    return file


async def test_a_library_file_round_trips_through_the_scope_constraint(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """`files_0002`: 'library' is an allowed scope, purposes live in the metadata."""
    book = library_file(clock, metadata={"pages": 320, "outline": [{"title": "I"}]})

    await uow.files.add(book)
    loaded = await uow.files.get(book.id)

    assert loaded == book
    assert loaded is not None and loaded.purpose == FilePurpose.LIBRARY_BOOK


async def test_library_bytes_are_counted_apart_from_the_study_quota(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """`used_bytes` of the library scope ignores student files and the reverse."""
    owner = uuid4()
    await uow.files.add(library_file(clock, owner_id=owner, byte_size=70))
    await uow.files.add(library_file(clock, owner_id=owner, byte_size=30))
    await uow.files.add(make_file(clock, owner_id=owner, byte_size=5))

    assert await uow.files.used_bytes(owner, FileScope.LIBRARY, None) == 100
    assert await uow.files.used_bytes(owner, FileScope.STUDENT, None) == 5


async def test_the_cleanup_query_never_lists_library_files(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """Even a library row with a past `expires_at` is left alone (FILE-6)."""
    old = clock.now() - timedelta(days=1)
    book = library_file(clock, expires_at=old)
    mail = make_file(clock, scope=FileScope.MAIL, expires_at=old)
    await uow.files.add(book)
    await uow.files.add(mail)

    due = await uow.files.list_expired(expired_term_ids=[], now=clock.now(), limit=10)

    assert [file.id for file in due] == [mail.id]


async def test_owner_listings_and_search_skip_library_files(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """My files, the assistant's file search and account deletion leave them out."""
    owner = uuid4()
    book = library_file(clock, owner_id=owner)
    note = make_file(clock, owner_id=owner)
    await uow.files.add(book)
    await uow.files.add(note)
    await uow.files.set_text(book.id, 9, "evergreen text")
    await uow.files.set_text(note.id, 9, "evergreen text")

    mine = await uow.files.list_for_owner(owner, purpose=None, after=None, limit=10)
    ready = await uow.files.list_ready(owner, 10)
    every = await uow.files.list_for_owner_all(owner, 10)
    found = await uow.files.search(owner, "evergreen", 10)

    for listing in (mine, ready, every, found):
        assert [file.id for file in listing] == [note.id]


async def test_delete_rows_removes_a_library_file_for_good(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """`FilesApi.delete_file` ends with the row gone."""
    book = library_file(clock)
    await uow.files.add(book)

    await uow.files.delete_rows([book.id])

    assert await uow.files.get(book.id) is None
