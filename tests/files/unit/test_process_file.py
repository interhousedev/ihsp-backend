"""FILE-7, UF-WEB-18 step 3: text extraction, sidecar, index and readiness."""

from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import (
    DOCX_TYPE,
    PDF_TYPE,
    PNG_BYTES,
    make_docx,
    make_pdf,
    sha256_b64,
    upload_and_complete,
    upload_ready,
)


async def test_pdf_text_is_stored_next_to_the_object_and_the_file_is_ready(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-7: the text goes to ``{key}.txt``; pages are kept in metadata."""
    file_id = await upload_ready(
        fakes,
        student,
        name="physics.pdf",
        data=make_pdf("Newton laws", "Second page"),
        content_type=PDF_TYPE,
    )

    file = fakes.db.row(file_id)
    sidecar = fakes.storage.objects[file.key + ".txt"]
    assert file.status == FileStatus.READY
    assert "Newton laws" in sidecar.data.decode()
    assert "Second page" in sidecar.data.decode()
    assert sidecar.content_type == "text/plain; charset=utf-8"
    assert file.text_bytes == len(sidecar.data)
    assert file.metadata == {"pages": 2, "page_starts": [0, 12]}


async def test_docx_paragraphs_and_tables_are_extracted_in_order(
    fakes: FilesFakes, student: Actor
) -> None:
    """python-docx: paragraphs and table rows."""
    data = make_docx("Intro paragraph", table=[["Name", "Mark"], ["Alice", "5"]])
    file_id = await upload_ready(
        fakes, student, name="journal.docx", data=data, content_type=DOCX_TYPE
    )

    file = fakes.db.row(file_id)
    text = fakes.storage.objects[file.text_key].data.decode()
    assert text.splitlines() == ["Intro paragraph", "Name\tMark", "Alice\t5"]


async def test_plain_text_is_decoded_with_replacement(
    fakes: FilesFakes, student: Actor
) -> None:
    """TXT/MD: UTF-8, errors replaced."""
    data = "Привет, мир".encode() + b" \xff end"
    file_id = await upload_ready(
        fakes, student, name="a.txt", data=data, content_type="text/plain"
    )

    file = fakes.db.row(file_id)
    text = fakes.storage.objects[file.key + ".txt"].data.decode()
    assert text.startswith("Привет, мир")
    assert text.endswith("� end")


async def test_text_over_100_kb_is_stored_but_marked_too_large_for_the_assistant(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-7: text_bytes keeps the size; assistant_ready is False above 100 KB."""
    data = ("word " * 30000).encode()
    file_id = await upload_ready(
        fakes, student, name="big.txt", data=data, content_type="text/plain"
    )

    view = await fakes.services.get_file.execute(student, file_id)

    assert view.file.text_bytes is not None and view.file.text_bytes > 100 * 1024
    assert view.assistant_ready is False


async def test_small_text_is_ready_for_the_assistant(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-7: text up to 100 KB can be used by the assistant."""
    file_id = await upload_ready(
        fakes, student, name="a.txt", data=b"hello there", content_type="text/plain"
    )

    view = await fakes.services.get_file.execute(student, file_id)

    assert view.assistant_ready is True


async def test_images_become_ready_without_text(
    fakes: FilesFakes, student: Actor
) -> None:
    """No text for PNG: ready, text_bytes null, no sidecar."""
    file_id = await upload_ready(
        fakes, student, name="a.png", data=PNG_BYTES, content_type="image/png"
    )

    file = fakes.db.row(file_id)
    assert file.status == FileStatus.READY
    assert file.text_bytes is None
    assert file.key + ".txt" not in fakes.storage.objects


async def test_a_damaged_pdf_is_still_ready_but_without_text(
    fakes: FilesFakes, student: Actor
) -> None:
    """Extraction errors: ready with text_bytes null (usable, not for the assistant)."""
    data = b"%PDF-1.4\n1 0 obj\n<< /Broken"
    file_id = await upload_ready(
        fakes, student, name="broken.pdf", data=data, content_type=PDF_TYPE
    )

    file = fakes.db.row(file_id)
    assert file.status == FileStatus.READY
    assert file.text_bytes is None


async def test_a_pdf_without_text_has_no_sidecar(
    fakes: FilesFakes, student: Actor
) -> None:
    """Image-only PDFs give no text."""
    file_id = await upload_ready(
        fakes, student, name="scan.pdf", data=make_pdf(""), content_type=PDF_TYPE
    )

    file = fakes.db.row(file_id)
    assert file.status == FileStatus.READY
    assert file.text_bytes is None


async def test_processing_twice_changes_nothing(
    fakes: FilesFakes, student: Actor
) -> None:
    """The task is idempotent (at-least-once delivery)."""
    file_id = await upload_ready(
        fakes, student, name="a.txt", data=b"hello", content_type="text/plain"
    )
    before = fakes.db.row(file_id).updated_at

    fakes.clock.advance(minutes=5)
    await fakes.services.process_file.execute(file_id)

    assert fakes.db.row(file_id).updated_at == before


async def test_a_file_that_is_not_processing_is_left_alone(
    fakes: FilesFakes, student: Actor
) -> None:
    """Pending files are not processed."""
    ticket = await fakes.services.request_upload.execute(
        student,
        name="a.txt",
        size=5,
        content_type="text/plain",
        sha256_b64=sha256_b64(b"hello"),
        purpose=FilePurpose.LINK,
    )

    await fakes.services.process_file.execute(ticket.view.file.id)

    assert fakes.db.row(ticket.view.file.id).status == FileStatus.PENDING


async def test_an_object_that_vanished_is_rejected_not_retried_forever(
    fakes: FilesFakes, student: Actor
) -> None:
    """The sweep must not re-kick a file whose object is gone."""
    view = await upload_and_complete(
        fakes, student, name="a.txt", data=b"hello", content_type="text/plain"
    )
    fakes.storage.objects.pop(view.file.key)

    await fakes.services.process_file.execute(view.file.id)

    row = fakes.db.row(view.file.id)
    assert row.status == FileStatus.REJECTED
    assert row.reject_reason == "files/processing-failed"
