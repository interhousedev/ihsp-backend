"""FILE-2: after the upload the backend checks size, checksum and the real type."""

from collections.abc import Callable

from app.modules.files.domain.errors import StoredFileNotFoundError, UploadMissingError
from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import (
    DOCX_TYPE,
    EXE_BYTES,
    PDF_TYPE,
    PNG_BYTES,
    make_docx,
    make_pdf,
    sha256_b64,
    upload_and_complete,
)

import pytest


async def test_a_good_pdf_becomes_processing_and_is_queued(
    fakes: FilesFakes, student: Actor
) -> None:
    """The first bytes say PDF: processing, and files.process is kicked."""
    data = make_pdf("Hello")

    view = await upload_and_complete(
        fakes, student, name="a.pdf", data=data, content_type=PDF_TYPE
    )

    assert view.file.status == FileStatus.PROCESSING
    assert view.file.content_type == PDF_TYPE
    assert fakes.kicker.calls == [("files.process", {"file_id": str(view.file.id)})]


async def test_a_docx_is_recognised_from_its_first_bytes(
    fakes: FilesFakes, student: Actor
) -> None:
    """OOXML files are accepted when libmagic sees the OOXML type."""
    view = await upload_and_complete(
        fakes,
        student,
        name="a.docx",
        data=make_docx("hi"),
        content_type=DOCX_TYPE,
    )

    assert view.file.status == FileStatus.PROCESSING


async def test_a_pdf_whose_bytes_are_a_png_is_rejected_and_deleted(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-2: files/type-mismatch -> rejected, the object is deleted at once."""
    view = await upload_and_complete(
        fakes, student, name="a.pdf", data=PNG_BYTES, content_type=PDF_TYPE
    )

    assert view.file.status == FileStatus.REJECTED
    assert view.file.reject_reason == "files/type-mismatch"
    assert view.file.key not in fakes.storage.objects
    assert fakes.kicker.calls == []


async def test_an_executable_renamed_to_pdf_is_rejected(
    fakes: FilesFakes, student: Actor
) -> None:
    """A Windows executable is not a PDF."""
    view = await upload_and_complete(
        fakes, student, name="a.pdf", data=EXE_BYTES, content_type=PDF_TYPE
    )

    assert view.file.reject_reason == "files/type-mismatch"


async def test_a_text_file_with_text_content_is_accepted(
    fakes: FilesFakes, student: Actor
) -> None:
    """TXT and MD pass when the content is text."""
    view = await upload_and_complete(
        fakes,
        student,
        name="notes.md",
        data="# Заголовок\n\ntext".encode(),
        content_type="text/markdown",
    )

    assert view.file.status == FileStatus.PROCESSING
    assert view.file.content_type == "text/markdown"


async def test_binary_content_in_a_txt_file_is_rejected(
    fakes: FilesFakes, student: Actor
) -> None:
    """Text files must be text."""
    view = await upload_and_complete(
        fakes,
        student,
        name="notes.txt",
        data=b"\xff\xfe\x00\x01" * 20,
        content_type="text/plain",
    )

    assert view.file.reject_reason == "files/type-mismatch"


async def test_complete_without_an_upload_is_a_conflict(
    fakes: FilesFakes, student: Actor
) -> None:
    """files/upload-missing (409): nothing is in storage."""
    ticket = await fakes.services.request_upload.execute(
        student,
        name="a.pdf",
        size=10,
        content_type=PDF_TYPE,
        sha256_b64=sha256_b64(b"x"),
        purpose=FilePurpose.LINK,
    )

    with pytest.raises(UploadMissingError) as caught:
        await fakes.services.complete_upload.execute(student, ticket.view.file.id)

    assert caught.value.status == 409
    assert fakes.db.row(ticket.view.file.id).status == FileStatus.PENDING


async def test_an_object_of_another_size_is_rejected(
    fakes: FilesFakes, student: Actor
) -> None:
    """The real size must equal the declared size."""
    data = make_pdf("Hello")
    ticket = await fakes.services.request_upload.execute(
        student,
        name="a.pdf",
        size=len(data),
        content_type=PDF_TYPE,
        sha256_b64=sha256_b64(data),
        purpose=FilePurpose.LINK,
    )
    key = fakes.db.row(ticket.view.file.id).key
    fakes.storage.force_object(key, data + b"extra")

    view = await fakes.services.complete_upload.execute(student, ticket.view.file.id)

    assert view.file.reject_reason == "files/checksum-mismatch"


async def test_an_object_with_another_checksum_is_rejected(
    fakes: FilesFakes, student: Actor
) -> None:
    """The stored checksum must be the declared one."""
    data = make_pdf("Hello")
    other = make_pdf("Jello")
    assert len(other) == len(data)
    ticket = await fakes.services.request_upload.execute(
        student,
        name="a.pdf",
        size=len(data),
        content_type=PDF_TYPE,
        sha256_b64=sha256_b64(data),
        purpose=FilePurpose.LINK,
    )
    key = fakes.db.row(ticket.view.file.id).key
    fakes.storage.force_object(key, other)

    view = await fakes.services.complete_upload.execute(student, ticket.view.file.id)

    assert view.file.reject_reason == "files/checksum-mismatch"
    assert key not in fakes.storage.objects


async def test_completing_twice_is_harmless(fakes: FilesFakes, student: Actor) -> None:
    """A second complete returns the file and queues nothing more."""
    data = make_pdf("Hello")
    view = await upload_and_complete(
        fakes, student, name="a.pdf", data=data, content_type=PDF_TYPE
    )

    again = await fakes.services.complete_upload.execute(student, view.file.id)

    assert again.file.status == FileStatus.PROCESSING
    assert len(fakes.kicker.calls) == 1


async def test_only_the_owner_can_complete(
    fakes: FilesFakes, student: Actor, make_actor: Callable[..., Actor]
) -> None:
    """Strangers get NotFound, not Forbidden."""
    data = make_pdf("Hello")
    view = await upload_and_complete(
        fakes, student, name="a.pdf", data=data, content_type=PDF_TYPE
    )
    stranger = make_actor(*student.roles)

    with pytest.raises(StoredFileNotFoundError):
        await fakes.services.complete_upload.execute(stranger, view.file.id)
