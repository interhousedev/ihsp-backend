"""LIB-3: bulk import of books from a CSV file (use case)."""

from uuid import UUID

from app.modules.library.domain.catalogue_errors import ImportInvalidError
from app.modules.library.domain.enums import ItemStatus, TextStatus
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.ids import new_id
from tests.fakes.library.catalogue_files import FakeScanFilesApi
from tests.fakes.tasks import FakeTaskKicker

import pytest

HEADER = "file_name,title,authors,language,type,subjects,rights,reference\n"


def _upload(files: FakeScanFilesApi, owner: Actor, name: str, data: bytes) -> UUID:
    return files.add_file(
        owner_id=owner.user_id,
        name=name,
        data=data,
        scope=FileScope.LIBRARY,
        purpose=FilePurpose.LIBRARY_BOOK,
        content_type="application/pdf" if name.endswith(".pdf") else "text/csv",
    )


async def test_good_rows_become_drafts_with_files_and_bad_rows_are_listed(
    library: LibraryServices,
    files_api: FakeScanFilesApi,
    librarian: Actor,
    kicker: FakeTaskKicker,
) -> None:
    """LIB-3: drafts for good rows (file attached, scan queued); errors by row."""
    await library.taxonomy.create_subject.execute(librarian, name={"en": "Physics"})
    pdf = _upload(files_api, librarian, "physics10.pdf", b"%PDF-1.4")
    csv_file = _upload(
        files_api,
        librarian,
        "books.csv",
        (
            HEADER
            + "physics10.pdf,Physics 10,A,uz_latn,textbook,Physics,official,Order 1\n"
            + "missing.pdf,Lost book,B,uz_latn,textbook,Physics,official,Order 2\n"
            + ",,C,uz_latn,textbook,Physics,,\n"
            + ",Chemistry,D,uz_latn,textbook,Chemistry,official,Order 3\n"
        ).encode(),
    )

    result = await library.catalogue.import_books.execute(librarian, csv_file)

    assert result.created == 1
    assert [e.row for e in result.errors] == [3, 4, 5]
    assert "missing.pdf" in result.errors[0].message
    page = await library.catalogue.list_books.execute(librarian)
    (row,) = page.items
    assert row.card.title == "Physics 10" and row.status is ItemStatus.DRAFT
    assert row.text_status is TextStatus.PENDING
    assert kicker.names() == ["library.process_item_file"]
    assert kicker.calls[0][1]["file_id"] == str(pdf)


async def test_a_row_without_a_file_is_a_draft_without_files(
    library: LibraryServices,
    files_api: FakeScanFilesApi,
    librarian: Actor,
    kicker: FakeTaskKicker,
) -> None:
    """LIB-3: files can be attached later in the editor."""
    csv_file = _upload(
        files_api,
        librarian,
        "books.csv",
        (HEADER + ",Kitob,A,uz_latn,other,,official,Order 1\n").encode(),
    )

    result = await library.catalogue.import_books.execute(librarian, csv_file)

    assert result.created == 1 and result.errors == []
    assert kicker.calls == []


async def test_error_messages_come_from_the_translations(
    library: LibraryServices,
    files_api: FakeScanFilesApi,
    librarian: Actor,
) -> None:
    """LIB-3: the message is a translated sentence with the column named."""
    csv_file = _upload(
        files_api,
        librarian,
        "books.csv",
        (HEADER + ",,A,uz_latn,other,,official,Order 1\n").encode(),
    )

    result = await library.catalogue.import_books.execute(librarian, csv_file)

    assert result.errors[0].message == 'Column "title" is empty.'


async def test_only_the_librarians_own_readable_csv_is_imported(
    library: LibraryServices,
    files_api: FakeScanFilesApi,
    librarian: Actor,
    other_librarian: Actor,
    student: Actor,
) -> None:
    """LIB-3: a stranger's file, a missing file and a binary file are refused."""
    theirs = _upload(files_api, other_librarian, "books.csv", b"title,rights\n")
    binary = _upload(files_api, librarian, "books.csv", b"\xff\xfe\x00bad")

    with pytest.raises(ImportInvalidError):
        await library.catalogue.import_books.execute(librarian, theirs)
    with pytest.raises(ImportInvalidError):
        await library.catalogue.import_books.execute(librarian, new_id())
    with pytest.raises(ImportInvalidError):
        await library.catalogue.import_books.execute(librarian, binary)
    with pytest.raises(ForbiddenError):
        await library.catalogue.import_books.execute(student, theirs)
