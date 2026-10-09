"""LIB-3, FILE-6: library files are never cleaned up, listed as My files or deleted
with the account."""

from datetime import timedelta
from uuid import UUID, uuid4

from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileScope
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import PDF_TYPE, make_pdf, upload_ready


async def _library_file(fakes: FilesFakes, owner: Actor) -> UUID:
    return await upload_ready(
        fakes,
        owner,
        name="book.pdf",
        data=make_pdf("Evergreen"),
        content_type=PDF_TYPE,
        purpose=FilePurpose.LIBRARY_BOOK,
    )


async def test_library_files_never_get_an_expiry_date(fakes: FilesFakes) -> None:
    """FILE-6 applies to student and mail files only: `expires_days` is ignored."""
    ref = await fakes.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.LIBRARY,
        purpose=FilePurpose.LIBRARY_MATERIAL,
        name="a.pdf",
        data=make_pdf("x"),
        expires_days=30,
    )

    assert fakes.db.row(ref.id).expires_at is None


async def test_cleanup_skips_library_files_even_with_an_expiry_date(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """The cleanup job's query leaves the scope out altogether."""
    file_id = await _library_file(fakes, librarian)
    row = fakes.db.row(file_id)
    row.expires_at = fakes.clock.now() - timedelta(days=1)
    fakes.clock.advance(days=400)

    deleted = await fakes.services.cleanup_expired.execute()

    assert deleted == 0
    assert fakes.db.row(file_id).status == FileStatus.READY
    assert row.key in fakes.storage.objects


async def test_the_term_warning_does_not_count_library_files(
    fakes: FilesFakes, student: Actor
) -> None:
    """Warnings are about the student's term files; materials stay out of them."""
    term = uuid4()
    fakes.terms.current = term
    await upload_ready(
        fakes,
        student,
        name="notes.pdf",
        data=make_pdf("mine"),
        content_type=PDF_TYPE,
        purpose=FilePurpose.LIBRARY_MATERIAL,
    )

    async with fakes.db.uow() as uow:
        assert await uow.files.student_term_ids() == []
        assert await uow.files.term_owner_counts(term) == []


async def test_library_files_are_not_in_my_files(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """My files shows study files; the library has its own pages."""
    await _library_file(fakes, librarian)

    page = await fakes.services.list_my_files.execute(librarian)

    assert page.items == []
    assert await fakes.services.public.list_owned(librarian.user_id, limit=10) == []
    assert await fakes.services.public.search_text(librarian.user_id, "Evergreen") == []


async def test_deleting_an_account_leaves_library_files_to_the_library(
    fakes: FilesFakes, student: Actor
) -> None:
    """Published materials stay under 'alumnus' unless the library says otherwise."""
    material = await upload_ready(
        fakes,
        student,
        name="notes.pdf",
        data=make_pdf("Published"),
        content_type=PDF_TYPE,
        purpose=FilePurpose.LIBRARY_MATERIAL,
    )
    private = await upload_ready(
        fakes,
        student,
        name="diary.pdf",
        data=make_pdf("Private"),
        content_type=PDF_TYPE,
    )

    deleted = await fakes.services.delete_owner_files.execute(student.user_id)

    assert deleted == 1
    assert fakes.db.row(private).status == FileStatus.DELETED
    assert fakes.db.row(material).status == FileStatus.READY
