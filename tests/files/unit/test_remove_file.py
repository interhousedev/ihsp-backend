"""LIB-3 (files part): FilesApi.delete_file, the library's way to clean up for good."""

from dataclasses import replace
from uuid import uuid4

from app.modules.files.application.request_upload import UploadTicket
from app.modules.files.domain.errors import QuotaExceededError, StoredFileNotFoundError
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import DEFAULT_LIMITS, FilesFakes, build_files_fakes
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import PDF_TYPE, make_pdf, sha256_b64, upload_ready

import pytest

MATERIAL = FilePurpose.LIBRARY_MATERIAL


async def test_the_bytes_the_text_sidecar_and_the_row_are_gone(
    fakes: FilesFakes, student: Actor
) -> None:
    """Hard delete: nothing is left to restore, `get` answers None."""
    file_id = await upload_ready(
        fakes,
        student,
        name="notes.pdf",
        data=make_pdf("Searchable text"),
        content_type=PDF_TYPE,
        purpose=MATERIAL,
    )
    row = fakes.db.row(file_id)
    assert row.text_key in fakes.storage.objects

    await fakes.services.public.delete_file(file_id)

    assert row.key not in fakes.storage.objects
    assert row.text_key not in fakes.storage.objects
    assert fakes.db.all_rows() == []
    assert file_id not in fakes.db.store.texts
    assert await fakes.services.public.get(file_id) is None


async def test_deleting_twice_or_an_unknown_file_is_fine(
    fakes: FilesFakes, student: Actor
) -> None:
    """Idempotent: cleanup jobs can be retried."""
    file_id = await upload_ready(
        fakes,
        student,
        name="notes.pdf",
        data=make_pdf("x"),
        content_type=PDF_TYPE,
        purpose=MATERIAL,
    )

    await fakes.services.public.delete_file(file_id)
    await fakes.services.public.delete_file(file_id)
    await fakes.services.public.delete_file(uuid4())


async def test_a_file_that_was_never_completed_can_be_deleted_too(
    fakes: FilesFakes, student: Actor
) -> None:
    """Pending uploads (no object yet) are removed without error."""
    ticket = await fakes.services.request_upload.execute(
        student,
        name="a.pdf",
        size=3,
        content_type=PDF_TYPE,
        sha256_b64=sha256_b64(b"abc"),
        purpose=MATERIAL,
    )

    await fakes.services.public.delete_file(ticket.view.file.id)

    assert fakes.db.all_rows() == []


async def test_deleting_frees_the_library_quota(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """A withdrawn material gives its space back."""
    limits = replace(DEFAULT_LIMITS, library_student_quota_bytes=10)
    fakes = build_files_fakes(clock, kicker, limits=limits)

    async def upload() -> UploadTicket:
        return await fakes.services.request_upload.execute(
            student,
            name="a.pdf",
            size=10,
            content_type=PDF_TYPE,
            sha256_b64=sha256_b64(b"x" * 10),
            purpose=MATERIAL,
        )

    first = await upload()
    with pytest.raises(QuotaExceededError):
        await upload()

    await fakes.services.public.delete_file(first.view.file.id)

    await upload()


async def test_transfer_ownership_frees_the_quota_and_the_owner_loses_the_file(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """An adopted file stops counting to the student and cannot be deleted by them."""
    limits = replace(DEFAULT_LIMITS, library_student_quota_bytes=10)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    ticket = await fakes.services.request_upload.execute(
        student,
        name="a.pdf",
        size=10,
        content_type=PDF_TYPE,
        sha256_b64=sha256_b64(b"x" * 10),
        purpose=MATERIAL,
    )
    file_id = ticket.view.file.id
    system_id = uuid4()

    await fakes.services.public.transfer_ownership([file_id, uuid4()], system_id)

    assert fakes.db.row(file_id).owner_id == system_id
    with pytest.raises(StoredFileNotFoundError):
        await fakes.services.delete_file.execute(student, file_id)
    assert fakes.db.row(file_id).owner_id == system_id
    await fakes.services.request_upload.execute(
        student,
        name="b.pdf",
        size=10,
        content_type=PDF_TYPE,
        sha256_b64=sha256_b64(b"y" * 10),
        purpose=MATERIAL,
    )
