"""NB-SRC-FILE: FilesApi.read_text_with_pages and the page offsets stored on upload."""

from uuid import uuid4

from app.modules.files.domain.errors import (
    FileDeletedError,
    NoTextError,
    StoredFileNotFoundError,
)
from app.shared.actor import Actor
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import PDF_TYPE, PNG_BYTES, make_pdf, upload_ready

import pytest


async def test_process_file_stores_the_page_offsets_next_to_the_page_count(
    fakes: FilesFakes, student: Actor
) -> None:
    """The metadata keeps pages and page_starts of the stored sidecar text."""
    file_id = await upload_ready(
        fakes,
        student,
        name="three.pdf",
        data=make_pdf("Alpha one", "Beta two", "Gamma three"),
        content_type=PDF_TYPE,
    )

    file = fakes.db.row(file_id)
    text = fakes.storage.objects[file.text_key].data.decode()
    assert file.metadata == {"pages": 3, "page_starts": [0, 10, 19]}
    assert [text[start] for start in file.metadata["page_starts"]] == ["A", "B", "G"]


async def test_a_pdf_without_text_stores_no_offsets(
    fakes: FilesFakes, student: Actor
) -> None:
    """A scan has nothing to point into: only the page count is kept."""
    file_id = await upload_ready(
        fakes, student, name="scan.pdf", data=make_pdf("", ""), content_type=PDF_TYPE
    )

    assert fakes.db.row(file_id).metadata == {"pages": 2}


async def test_the_whole_text_comes_with_the_page_offsets(
    fakes: FilesFakes, student: Actor
) -> None:
    """FilesApi.read_text_with_pages returns the sidecar text and page_starts."""
    file_id = await upload_ready(
        fakes,
        student,
        name="three.pdf",
        data=make_pdf("Alpha one", "Beta two", "Gamma three"),
        content_type=PDF_TYPE,
    )

    full = await fakes.services.public.read_text_with_pages(file_id)

    assert full.file_id == file_id
    assert full.text == "Alpha one\nBeta two\nGamma three"
    assert full.page_starts == (0, 10, 19)


async def test_the_use_case_is_wired_and_matches_the_api(
    fakes: FilesFakes, student: Actor
) -> None:
    """services.read_full_text is the use case behind the API method."""
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=make_pdf("One", "Two"), content_type=PDF_TYPE
    )

    direct = await fakes.services.read_full_text.execute(file_id)

    assert direct == await fakes.services.public.read_text_with_pages(file_id)


async def test_text_is_not_split_into_8_kb_pages(
    fakes: FilesFakes, student: Actor
) -> None:
    """Unlike read_text_page, the text of a big file comes in one piece."""
    text = " ".join(f"word{i:05d}" for i in range(4000))
    file_id = await upload_ready(
        fakes, student, name="big.txt", data=text.encode(), content_type="text/plain"
    )

    full = await fakes.services.public.read_text_with_pages(file_id)

    assert full.text == text and len(full.text.encode()) > 8192
    assert full.page_starts == ()


async def test_files_processed_before_offsets_existed_have_an_empty_tuple(
    fakes: FilesFakes, student: Actor
) -> None:
    """Older files have only 'pages' in their metadata."""
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=make_pdf("One", "Two"), content_type=PDF_TYPE
    )
    fakes.db.row(file_id).metadata = {"pages": 2}

    full = await fakes.services.public.read_text_with_pages(file_id)

    assert full.text == "One\nTwo" and full.page_starts == ()


@pytest.mark.parametrize(
    "stored", ["oops", [0, "x"], [0, 999], [-1, 0], {"a": 1}], ids=str
)
async def test_unusable_stored_offsets_are_ignored(
    fakes: FilesFakes, student: Actor, stored: object
) -> None:
    """Damaged metadata never produces offsets outside the text."""
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=make_pdf("One", "Two"), content_type=PDF_TYPE
    )
    fakes.db.row(file_id).metadata = {"pages": 2, "page_starts": stored}

    full = await fakes.services.public.read_text_with_pages(file_id)

    assert full.page_starts == ()


async def test_a_file_without_text_raises_no_text(
    fakes: FilesFakes, student: Actor
) -> None:
    """Images (and scans) have no sidecar."""
    file_id = await upload_ready(
        fakes, student, name="a.png", data=PNG_BYTES, content_type="image/png"
    )

    with pytest.raises(NoTextError):
        await fakes.services.public.read_text_with_pages(file_id)


async def test_a_missing_file_is_not_found(fakes: FilesFakes) -> None:
    """Unknown id."""
    with pytest.raises(StoredFileNotFoundError):
        await fakes.services.public.read_text_with_pages(uuid4())


async def test_a_deleted_file_is_gone(fakes: FilesFakes, student: Actor) -> None:
    """Deleted files can no longer be read (FILE-6)."""
    file_id = await upload_ready(
        fakes, student, name="a.txt", data=b"some text", content_type="text/plain"
    )
    await fakes.services.delete_file.execute(student, file_id)

    with pytest.raises(FileDeletedError):
        await fakes.services.public.read_text_with_pages(file_id)
