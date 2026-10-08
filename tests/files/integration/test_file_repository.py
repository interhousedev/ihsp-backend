"""The SQL repository against real PostgreSQL (tsvector, JSONB, advisory lock)."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.infrastructure.uow import SqlFilesUnitOfWork
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

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


def make_file(clock: FixedClock, **fields: Any) -> StoredFile:
    """A StoredFile with defaults for everything a test does not care about."""
    file_id = fields.pop("id", None) or new_id()
    values: dict[str, Any] = {
        "id": file_id,
        "owner_id": uuid4(),
        "scope": FileScope.STUDENT,
        "purpose": FilePurpose.LINK,
        "key": f"student/2026-10/{file_id}.txt",
        "name": "a.txt",
        "content_type": "text/plain",
        "byte_size": 10,
        "checksum": "sum",
        "status": FileStatus.READY,
        "created_at": clock.now(),
        "updated_at": clock.now(),
    }
    values.update(fields)
    return StoredFile(**values)


async def test_a_file_survives_a_round_trip_with_purpose_and_metadata(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """Purpose lives in the metadata column next to the module's own keys."""
    term = uuid4()
    original = make_file(
        clock,
        purpose=FilePurpose.AI_UPLOAD,
        metadata={"pages": 12},
        term_id=term,
        text_bytes=5,
        expires_at=clock.now() + timedelta(days=30),
        reject_reason=None,
    )

    await uow.files.add(original)
    loaded = await uow.files.get(original.id)

    assert loaded == original
    assert loaded is not None and loaded.metadata == {"pages": 12}
    assert await uow.files.get(uuid4()) is None


async def test_save_updates_the_row(uow: SqlFilesUnitOfWork, clock: FixedClock) -> None:
    """Status, name and metadata changes are written."""
    file = make_file(clock, status=FileStatus.PROCESSING)
    await uow.files.add(file)

    file.mark_ready(clock.now(), text_bytes=7, metadata={"pages": 3})
    file.rename("renamed.txt", clock.now())
    await uow.files.save(file)

    loaded = await uow.files.get(file.id)
    assert loaded is not None
    assert (loaded.status, loaded.name, loaded.text_bytes) == (
        FileStatus.READY,
        "renamed.txt",
        7,
    )
    assert loaded.metadata == {"pages": 3}
    assert loaded.purpose == FilePurpose.LINK


async def test_used_bytes_counts_live_files_of_the_term_for_students(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """FILE-5: SUM(byte_size) of pending, processing and ready files of the term."""
    owner, term, other_term = uuid4(), uuid4(), uuid4()
    for status, size, term_id in [
        (FileStatus.PENDING, 1, term),
        (FileStatus.PROCESSING, 10, term),
        (FileStatus.READY, 100, term),
        (FileStatus.REJECTED, 1000, term),
        (FileStatus.DELETED, 10000, term),
        (FileStatus.READY, 100000, other_term),
    ]:
        await uow.files.add(
            make_file(
                clock, owner_id=owner, status=status, byte_size=size, term_id=term_id
            )
        )
    await uow.files.add(
        make_file(clock, owner_id=uuid4(), byte_size=1000000, term_id=term)
    )

    used = await uow.files.used_bytes(owner, FileScope.STUDENT, term)

    assert used == 111
    assert await uow.files.used_bytes(owner, FileScope.STUDENT, None) == 0
    assert await uow.files.used_bytes(uuid4(), FileScope.STUDENT, term) == 0


async def test_used_bytes_for_staff_counts_everything_regardless_of_term(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """FILE-5: staff quota is a total over all their staff files."""
    owner = uuid4()
    for size in (5, 7):
        await uow.files.add(
            make_file(clock, owner_id=owner, scope=FileScope.STAFF, byte_size=size)
        )
    await uow.files.add(
        make_file(clock, owner_id=owner, scope=FileScope.MAIL, byte_size=1000)
    )

    assert await uow.files.used_bytes(owner, FileScope.STAFF, None) == 12


async def test_the_owner_lock_can_be_taken_twice_in_one_transaction(
    uow: SqlFilesUnitOfWork,
) -> None:
    """pg_advisory_xact_lock is re-entrant inside one transaction."""
    owner = uuid4()

    await uow.files.lock_owner(owner)
    await uow.files.lock_owner(owner)


async def test_listing_is_newest_first_filtered_and_paged_by_cursor(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """Cursor on (created_at, id); pending and deleted rows are hidden."""
    owner = uuid4()
    ids: list[UUID] = []
    for index in range(4):
        clock.advance(minutes=1)
        file = make_file(
            clock,
            owner_id=owner,
            purpose=FilePurpose.AI_UPLOAD if index == 1 else FilePurpose.LINK,
        )
        await uow.files.add(file)
        ids.append(file.id)
    await uow.files.add(make_file(clock, owner_id=owner, status=FileStatus.PENDING))
    gone = make_file(clock, owner_id=owner, status=FileStatus.DELETED)
    await uow.files.add(gone)

    page_one = await uow.files.list_for_owner(owner, purpose=None, after=None, limit=3)
    last = page_one[-1]
    page_two = await uow.files.list_for_owner(
        owner, purpose=None, after=(last.created_at, last.id), limit=3
    )
    only_chat = await uow.files.list_for_owner(
        owner, purpose=FilePurpose.AI_UPLOAD, after=None, limit=10
    )

    assert [f.id for f in page_one] == [ids[3], ids[2], ids[1]]
    assert [f.id for f in page_two] == [ids[0]]
    assert [f.id for f in only_chat] == [ids[1]]


async def test_list_ready_returns_only_ready_files_newest_first(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """Used by FilesApi.list_owned and the empty search."""
    owner = uuid4()
    first = make_file(clock, owner_id=owner)
    await uow.files.add(first)
    clock.advance(minutes=1)
    second = make_file(clock, owner_id=owner)
    await uow.files.add(second)
    for status in (FileStatus.PROCESSING, FileStatus.REJECTED, FileStatus.DELETED):
        await uow.files.add(make_file(clock, owner_id=owner, status=status))

    ready = await uow.files.list_ready(owner, 10)

    assert [f.id for f in ready] == [second.id, first.id]
    assert [f.id for f in await uow.files.list_ready(owner, 1)] == [second.id]


async def test_search_matches_words_and_ranks_by_relevance(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """to_tsvector('simple') on the text, plainto_tsquery on the query."""
    owner = uuid4()
    weak = make_file(clock, owner_id=owner, name="weak.txt")
    strong = make_file(clock, owner_id=owner, name="strong.txt")
    nothing = make_file(clock, owner_id=owner, name="nothing.txt")
    for file, text in [
        (weak, "A long story that mentions photosynthesis once among many words"),
        (strong, "photosynthesis photosynthesis photosynthesis"),
        (nothing, "chemistry and physics only"),
    ]:
        await uow.files.add(file)
        await uow.files.set_text(file.id, len(text.encode()), text)

    found = await uow.files.search(owner, "Photosynthesis", 10)

    assert {f.name for f in found} == {"weak.txt", "strong.txt"}
    assert found[0].name == "strong.txt"
    assert await uow.files.search(uuid4(), "photosynthesis", 10) == []
    both = await uow.files.search(owner, "chemistry physics", 10)
    assert [f.name for f in both] == ["nothing.txt"]


async def test_search_ignores_files_that_are_not_ready_or_not_indexed(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """Only ready files with a search vector are found."""
    owner = uuid4()
    processing = make_file(clock, owner_id=owner, status=FileStatus.PROCESSING)
    plain = make_file(clock, owner_id=owner)
    await uow.files.add(processing)
    await uow.files.add(plain)
    await uow.files.set_text(processing.id, 5, "needle")

    assert await uow.files.search(owner, "needle", 10) == []


async def test_headline_marks_the_match_and_keeps_context(
    uow: SqlFilesUnitOfWork,
) -> None:
    """ts_headline fragment with ``**`` around matches."""
    document = "Plants make food. Photosynthesis turns light into chemical energy."

    snippet = await uow.files.headline(document, "photosynthesis")

    assert "**Photosynthesis**" in snippet


async def test_mark_deleted_clears_text_size_and_search_vector(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """README -> Cleanup: rows are marked deleted and the vector is cleared."""
    owner = uuid4()
    file = make_file(clock, owner_id=owner)
    await uow.files.add(file)
    await uow.files.set_text(file.id, 6, "needle")
    assert len(await uow.files.search(owner, "needle", 5)) == 1
    now = clock.now() + timedelta(days=1)

    await uow.files.mark_deleted([file.id], now)

    assert await uow.files.search(owner, "needle", 5) == []
    loaded = await uow.files.get(file.id)
    assert loaded is not None
    assert (loaded.status, loaded.deleted_at, loaded.text_bytes) == (
        FileStatus.DELETED,
        now,
        None,
    )


async def test_expired_files_are_those_of_expired_terms_or_past_expires_at(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """The cleanup query: term-based for students, expires_at for everything."""
    old_term, new_term = uuid4(), uuid4()
    in_old_term = make_file(clock, term_id=old_term)
    in_new_term = make_file(clock, term_id=new_term)
    staff_in_old = make_file(clock, scope=FileScope.STAFF, term_id=old_term)
    mail_due = make_file(
        clock, scope=FileScope.MAIL, expires_at=clock.now() - timedelta(days=1)
    )
    mail_later = make_file(
        clock, scope=FileScope.MAIL, expires_at=clock.now() + timedelta(days=1)
    )
    already = make_file(clock, term_id=old_term, status=FileStatus.DELETED)
    for file in (in_old_term, in_new_term, staff_in_old, mail_due, mail_later, already):
        await uow.files.add(file)

    expired = await uow.files.list_expired(
        expired_term_ids=[old_term], now=clock.now(), limit=100
    )

    assert {f.id for f in expired} == {in_old_term.id, mail_due.id}
    assert await uow.files.student_term_ids() != []
    assert {in_old_term.term_id, in_new_term.term_id} <= set(
        await uow.files.student_term_ids()
    )


async def test_term_owner_counts_group_live_student_files_by_owner(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """The input of the expiry warning."""
    term, one, two = uuid4(), uuid4(), uuid4()
    for owner in (one, one, two):
        await uow.files.add(make_file(clock, owner_id=owner, term_id=term))
    await uow.files.add(
        make_file(clock, owner_id=two, term_id=term, status=FileStatus.REJECTED)
    )

    counts = dict(await uow.files.term_owner_counts(term))

    assert counts == {one: 2, two: 1}


async def test_stale_uploads_and_stale_processing_queries(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """purge_pending and sweep_processing read these."""
    old = clock.now() - timedelta(hours=30)
    pending_old = make_file(clock, status=FileStatus.PENDING, created_at=old)
    pending_new = make_file(clock, status=FileStatus.PENDING)
    rejected_old = make_file(clock, status=FileStatus.REJECTED, updated_at=old)
    stuck = make_file(
        clock,
        status=FileStatus.PROCESSING,
        updated_at=clock.now() - timedelta(minutes=11),
    )
    fine = make_file(clock, status=FileStatus.PROCESSING)
    for file in (pending_old, pending_new, rejected_old, stuck, fine):
        await uow.files.add(file)

    stale = await uow.files.list_stale_uploads(clock.now() - timedelta(hours=24), 10)
    processing = await uow.files.list_stale_processing(
        clock.now() - timedelta(minutes=10), 10
    )

    assert {f.id for f in stale} == {pending_old.id, rejected_old.id}
    assert [f.id for f in processing] == [stuck.id]


async def test_delete_rows_removes_them_and_get_many_skips_missing(
    uow: SqlFilesUnitOfWork, clock: FixedClock
) -> None:
    """Abandoned uploads are removed entirely."""
    keep, drop = make_file(clock), make_file(clock)
    await uow.files.add(keep)
    await uow.files.add(drop)

    await uow.files.delete_rows([drop.id])

    found = await uow.files.get_many([keep.id, drop.id, uuid4()])
    assert [f.id for f in found] == [keep.id]
    assert await uow.files.get_many([]) == []
