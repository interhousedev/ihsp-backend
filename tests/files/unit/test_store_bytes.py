"""FilesApi.store_bytes: server-side uploads by the bot, mail and LMS."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from app.modules.files.domain.errors import (
    FileTooLargeError,
    QuotaExceededError,
    TypeNotAllowedError,
)
from app.modules.files.domain.status import FileStatus
from app.shared.contracts.files import FilePurpose, FileScope
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import DEFAULT_LIMITS, FilesFakes, build_files_fakes
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import EXE_BYTES, PNG_BYTES, make_pdf

import pytest


async def test_a_pdf_from_the_bot_is_stored_and_queued_for_processing(
    fakes: FilesFakes,
) -> None:
    """Same validation as an upload; text extraction runs in the background."""
    owner = uuid4()
    data = make_pdf("From Telegram")

    ref = await fakes.services.public.store_bytes(
        owner_id=owner,
        scope=FileScope.STAFF,
        purpose=FilePurpose.LINK,
        name="lesson.pdf",
        data=data,
    )

    row = fakes.db.row(ref.id)
    assert ref.status == "processing"
    assert row.content_type == "application/pdf"
    assert fakes.storage.objects[row.key].data == data
    assert fakes.kicker.calls == [("files.process", {"file_id": str(ref.id)})]


async def test_a_wrong_type_from_the_bot_is_refused_outright(
    fakes: FilesFakes,
) -> None:
    """No rejected row: the call fails and nothing is stored."""
    with pytest.raises(TypeNotAllowedError):
        await fakes.services.public.store_bytes(
            owner_id=uuid4(),
            scope=FileScope.STAFF,
            purpose=FilePurpose.LINK,
            name="lesson.pdf",
            data=EXE_BYTES,
        )

    assert fakes.db.all_rows() == []
    assert fakes.storage.objects == {}


async def test_an_extension_that_is_not_allowed_is_refused(fakes: FilesFakes) -> None:
    """``.exe`` for a link or assistant file."""
    with pytest.raises(TypeNotAllowedError):
        await fakes.services.public.store_bytes(
            owner_id=uuid4(),
            scope=FileScope.STAFF,
            purpose=FilePurpose.AI_UPLOAD,
            name="a.exe",
            data=EXE_BYTES,
        )


async def test_a_file_over_the_limit_is_refused(
    clock: FixedClock, kicker: FakeTaskKicker
) -> None:
    """FILE-4: 100 MB per file also for server-side uploads."""
    limits = replace(DEFAULT_LIMITS, file_max_bytes=10)
    fakes = build_files_fakes(clock, kicker, limits=limits)

    with pytest.raises(FileTooLargeError):
        await fakes.services.public.store_bytes(
            owner_id=uuid4(),
            scope=FileScope.STAFF,
            purpose=FilePurpose.LINK,
            name="a.txt",
            data=b"x" * 11,
        )


async def test_mail_files_have_no_validation_and_are_ready_at_once(
    fakes: FilesFakes,
) -> None:
    """FILE-6: mail purpose allows any type; no text extraction."""
    ref = await fakes.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.MAIL,
        purpose=FilePurpose.MAIL,
        name="invoice.exe",
        data=EXE_BYTES,
        expires_days=30,
    )

    row = fakes.db.row(ref.id)
    assert row.status == FileStatus.READY
    assert row.expires_at == fakes.clock.now() + timedelta(days=30)
    assert row.key.startswith("mail/2026-10/")
    assert fakes.kicker.calls == []


async def test_mail_files_are_not_counted_against_a_quota(
    clock: FixedClock, kicker: FakeTaskKicker
) -> None:
    """Quota covers student and staff files only."""
    limits = replace(DEFAULT_LIMITS, staff_quota_bytes=1, student_quota_bytes=1)
    fakes = build_files_fakes(clock, kicker, limits=limits)

    await fakes.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.MAIL,
        purpose=FilePurpose.MAIL,
        name="a.bin",
        data=b"123456",
    )


async def test_server_side_uploads_respect_the_quota(
    clock: FixedClock, kicker: FakeTaskKicker
) -> None:
    """FILE-5: the bot cannot exceed the 10 GB staff quota either."""
    limits = replace(DEFAULT_LIMITS, staff_quota_bytes=6)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    owner = uuid4()
    await fakes.services.public.store_bytes(
        owner_id=owner,
        scope=FileScope.STAFF,
        purpose=FilePurpose.LINK,
        name="a.txt",
        data=b"123456",
    )

    with pytest.raises(QuotaExceededError):
        await fakes.services.public.store_bytes(
            owner_id=owner,
            scope=FileScope.STAFF,
            purpose=FilePurpose.LINK,
            name="b.txt",
            data=b"1",
        )

    assert len(fakes.storage.objects) == 1


async def test_student_files_from_the_server_belong_to_the_current_term(
    fakes: FilesFakes,
) -> None:
    """The term is resolved like for uploads."""
    term = uuid4()
    fakes.terms.current = term

    ref = await fakes.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.STUDENT,
        purpose=FilePurpose.AI_UPLOAD,
        name="pic.png",
        data=PNG_BYTES,
    )

    assert fakes.db.row(ref.id).term_id == term
    assert fakes.db.row(ref.id).key.startswith(f"student/{term}/")
