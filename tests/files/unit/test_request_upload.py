"""FILE-2, FILE-4, FILE-5, UF-WEB-07 (upload part): asking for an upload."""

from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from app.modules.files.application.request_upload import UploadTicket
from app.modules.files.domain.errors import (
    FileTooLargeError,
    InvalidChecksumError,
    QuotaExceededError,
    TypeNotAllowedError,
)
from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileScope
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import (
    DEFAULT_LIMITS,
    FilesFakes,
    build_files_fakes,
)
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import PDF_TYPE, sha256_b64

import pytest

PDF = b"%PDF-1.4 tiny"


async def ask(
    fakes: FilesFakes,
    actor: Actor,
    *,
    name: str = "notes.pdf",
    size: int | None = None,
    content_type: str = PDF_TYPE,
    purpose: FilePurpose = FilePurpose.LINK,
    data: bytes = PDF,
) -> UploadTicket:
    """Call request_upload with sensible defaults."""
    return await fakes.services.request_upload.execute(
        actor,
        name=name,
        size=len(data) if size is None else size,
        content_type=content_type,
        sha256_b64=sha256_b64(data),
        purpose=purpose,
    )


async def test_request_creates_a_pending_row_and_a_signed_put(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-2: the URL is bound to size, type and SHA-256; the row is pending."""
    term = uuid4()
    fakes.terms.current = term

    ticket = await ask(fakes, student, name="Lab report.pdf")

    file = fakes.db.row(ticket.view.file.id)
    assert file.status == FileStatus.PENDING
    assert file.owner_id == student.user_id
    assert file.scope == FileScope.STUDENT
    assert file.term_id == term
    assert file.name == "Lab report.pdf"
    assert file.byte_size == len(PDF)
    assert file.checksum == sha256_b64(PDF)
    assert file.key == f"student/{term}/{file.id}.pdf"
    assert ticket.upload.method == "PUT"
    assert ticket.upload.headers == {
        "Content-Type": PDF_TYPE,
        "x-amz-checksum-sha256": sha256_b64(PDF),
    }
    signed = fakes.storage.signatures[ticket.upload.url]
    assert (signed.key, signed.content_length) == (file.key, len(PDF))


async def test_the_key_never_contains_the_user_supplied_name(
    fakes: FilesFakes, student: Actor
) -> None:
    """README -> File.key: random, never built from the file name."""
    ticket = await ask(fakes, student, name="../../secret name.pdf")

    file = fakes.db.row(ticket.view.file.id)
    assert "secret" not in file.key
    assert file.name == "secret name.pdf"
    assert file.key.startswith("student/")


async def test_files_between_terms_get_a_month_label_in_their_key(
    fakes: FilesFakes, student: Actor
) -> None:
    """No term at all: the key falls back to yyyy-mm."""
    ticket = await ask(fakes, student)

    file = fakes.db.row(ticket.view.file.id)
    assert file.term_id is None
    assert file.key == f"student/2026-10/{file.id}.pdf"


async def test_staff_files_use_the_staff_scope_and_no_term(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """FILE-5: staff files are not tied to a term."""
    fakes.terms.current = uuid4()

    ticket = await ask(fakes, teacher)

    file = fakes.db.row(ticket.view.file.id)
    assert file.scope == FileScope.STAFF
    assert file.term_id is None


@pytest.mark.parametrize("name", ["virus.exe", "page.html", "archive.zip"])
async def test_a_type_that_is_not_allowed_is_refused(
    fakes: FilesFakes, student: Actor, name: str
) -> None:
    """FILE-4: only PDF, DOCX, PPTX, XLSX, TXT, MD, PNG, JPG."""
    with pytest.raises(TypeNotAllowedError):
        await ask(fakes, student, name=name, content_type="application/octet-stream")

    assert fakes.db.all_rows() == []


async def test_a_declared_type_that_does_not_fit_the_extension_is_refused(
    fakes: FilesFakes, student: Actor
) -> None:
    """The declared type is checked against the extension."""
    with pytest.raises(TypeNotAllowedError):
        await ask(fakes, student, name="a.pdf", content_type="image/png")


async def test_mail_is_not_an_upload_purpose(fakes: FilesFakes, student: Actor) -> None:
    """Only ai_upload and link can be requested through the API."""
    with pytest.raises(TypeNotAllowedError):
        await ask(fakes, student, purpose=FilePurpose.MAIL)


async def test_a_file_over_100_mb_is_refused(fakes: FilesFakes, student: Actor) -> None:
    """FILE-4: 100 MB per file."""
    with pytest.raises(FileTooLargeError):
        await ask(fakes, student, size=100 * 1024 * 1024 + 1)


async def test_a_malformed_checksum_is_refused(
    fakes: FilesFakes, student: Actor
) -> None:
    """The SHA-256 must be base64 of 32 bytes."""
    with pytest.raises(InvalidChecksumError):
        await fakes.services.request_upload.execute(
            student,
            name="a.pdf",
            size=3,
            content_type=PDF_TYPE,
            sha256_b64="zzz",
            purpose=FilePurpose.LINK,
        )


async def test_one_byte_under_the_quota_plus_two_bytes_is_refused(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """FILE-5: 1.5 GB - 1 byte used and a 2-byte file -> quota-exceeded (413)."""
    limits = replace(DEFAULT_LIMITS, file_max_bytes=2 * 1024**3)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    quota = DEFAULT_LIMITS.student_quota_bytes
    first = await ask(fakes, student, size=quota - 1, data=b"%PDF-1.4 big")
    assert first.view.file.byte_size == quota - 1

    with pytest.raises(QuotaExceededError) as caught:
        await ask(fakes, student, data=b"ab")

    assert caught.value.status == 413
    assert caught.value.code == "files/quota-exceeded"
    assert len(fakes.db.all_rows()) == 1


async def test_a_file_that_exactly_fills_the_quota_is_accepted(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """The quota is inclusive."""
    limits = replace(DEFAULT_LIMITS, student_quota_bytes=10)
    fakes = build_files_fakes(clock, kicker, limits=limits)

    await ask(fakes, student, data=b"1234567890")

    with pytest.raises(QuotaExceededError):
        await ask(fakes, student, data=b"x")


async def test_the_quota_lock_is_taken_before_the_check(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-5: parallel uploads are serialised by an advisory lock per owner."""
    await ask(fakes, student)

    assert fakes.db.log.locked == [student.user_id]


async def test_quota_counts_pending_processing_and_ready_but_not_deleted(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """Only live files count; deleting frees the space."""
    limits = replace(DEFAULT_LIMITS, student_quota_bytes=10)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    ticket = await ask(fakes, student, data=b"1234567890")
    with pytest.raises(QuotaExceededError):
        await ask(fakes, student, data=b"x")

    async with fakes.db.uow() as uow:
        await uow.files.mark_deleted([ticket.view.file.id], clock.now())
        await uow.commit()

    await ask(fakes, student, data=b"1234567890")


async def test_another_students_files_do_not_count(
    clock: FixedClock,
    kicker: FakeTaskKicker,
    student: Actor,
    make_actor: Callable[..., Actor],
) -> None:
    """The quota is per owner."""
    limits = replace(DEFAULT_LIMITS, student_quota_bytes=10)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    await ask(fakes, student, data=b"1234567890")

    await ask(fakes, make_actor(*student.roles), data=b"1234567890")


async def test_files_of_the_previous_term_do_not_count(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """FILE-5: quotas restart with the new term."""
    limits = replace(DEFAULT_LIMITS, student_quota_bytes=10)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    fakes.terms.current = uuid4()
    await ask(fakes, student, data=b"1234567890")

    fakes.terms.current = uuid4()

    await ask(fakes, student, data=b"1234567890")


async def test_staff_have_their_own_larger_quota(
    clock: FixedClock, kicker: FakeTaskKicker, teacher: Actor
) -> None:
    """FILE-5: staff 10 GB, over all their files."""
    limits = replace(DEFAULT_LIMITS, student_quota_bytes=10, staff_quota_bytes=20)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    await ask(fakes, teacher, data=b"1234567890")
    await ask(fakes, teacher, data=b"1234567890")

    with pytest.raises(QuotaExceededError):
        await ask(fakes, teacher, data=b"x")
