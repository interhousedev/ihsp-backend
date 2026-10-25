"""LMS video uploads: type, size, role and sniffed MIME of the `lms_video` purpose."""

from dataclasses import replace

from app.modules.files.domain.errors import FileTooLargeError, TypeNotAllowedError
from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose, FileScope
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import (
    DEFAULT_LIMITS,
    FilesFakes,
    build_files_fakes,
)
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import upload_and_complete

import pytest

VIDEO = FilePurpose.LMS_VIDEO
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
MOV = b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 64


@pytest.fixture
def small_videos(clock: FixedClock, kicker: FakeTaskKicker) -> FilesFakes:
    """Files whose video limit is 1 KiB."""
    return build_files_fakes(
        clock, kicker, limits=replace(DEFAULT_LIMITS, lms_video_max_bytes=1024)
    )


@pytest.mark.parametrize(
    ("name", "declared", "data"),
    [
        ("lesson.mp4", "video/mp4", MP4),
        ("lesson.webm", "video/webm", WEBM),
        ("lesson.mov", "video/quicktime", MOV),
    ],
)
async def test_course_staff_upload_mp4_webm_and_mov(
    fakes: FilesFakes, teacher: Actor, name: str, declared: str, data: bytes
) -> None:
    """The three allowed types pass; the row lives in the staff scope."""
    view = await upload_and_complete(
        fakes, teacher, name=name, data=data, content_type=declared, purpose=VIDEO
    )

    assert view.file.status == FileStatus.PROCESSING
    assert view.file.purpose == VIDEO
    assert view.file.scope == FileScope.STAFF


async def test_other_video_types_are_refused(fakes: FilesFakes, teacher: Actor) -> None:
    """An .avi (or .mkv) never gets a signed URL."""
    with pytest.raises(TypeNotAllowedError):
        await upload_and_complete(
            fakes,
            teacher,
            name="lesson.avi",
            data=MP4,
            content_type="video/x-msvideo",
            purpose=VIDEO,
        )


async def test_a_non_video_is_refused_for_the_video_purpose(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """A PDF cannot hide behind the `lms_video` purpose."""
    with pytest.raises(TypeNotAllowedError):
        await upload_and_complete(
            fakes,
            teacher,
            name="a.pdf",
            data=b"%PDF-1.4",
            content_type="application/pdf",
            purpose=VIDEO,
        )


async def test_a_video_is_refused_for_other_purposes(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """Plain uploads stay documents and images."""
    with pytest.raises(TypeNotAllowedError):
        await upload_and_complete(
            fakes,
            teacher,
            name="lesson.mp4",
            data=MP4,
            content_type="video/mp4",
            purpose=FilePurpose.LINK,
        )


async def test_the_size_limit_comes_from_the_setting(
    small_videos: FilesFakes, teacher: Actor
) -> None:
    """Over the video limit: too large (the 100 MiB general limit is not used)."""
    with pytest.raises(FileTooLargeError):
        await upload_and_complete(
            small_videos,
            teacher,
            name="lesson.mp4",
            data=MP4 + b"\x00" * 2000,
            content_type="video/mp4",
            purpose=VIDEO,
        )


async def test_a_video_may_be_bigger_than_the_general_limit(
    clock: FixedClock, kicker: FakeTaskKicker, teacher: Actor
) -> None:
    """The video limit replaces `file_max_bytes` for this purpose only."""
    fakes = build_files_fakes(
        clock,
        kicker,
        limits=replace(DEFAULT_LIMITS, file_max_bytes=100, lms_video_max_bytes=10_000),
    )

    view = await upload_and_complete(
        fakes,
        teacher,
        name="lesson.mp4",
        data=MP4,
        content_type="video/mp4",
        purpose=VIDEO,
    )

    assert view.file.status == FileStatus.PROCESSING


async def test_students_cannot_upload_videos(fakes: FilesFakes, student: Actor) -> None:
    """Only course staff roles may; students get a 403."""
    with pytest.raises(ForbiddenError):
        await upload_and_complete(
            fakes,
            student,
            name="lesson.mp4",
            data=MP4,
            content_type="video/mp4",
            purpose=VIDEO,
        )


async def test_an_exe_renamed_to_mp4_is_rejected_by_the_sniffed_type(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """The first bytes decide, not the name or the declared type."""
    view = await upload_and_complete(
        fakes,
        teacher,
        name="lesson.mp4",
        data=b"MZ" + b"\x90" * 64,
        content_type="video/mp4",
        purpose=VIDEO,
    )

    assert view.file.status == FileStatus.REJECTED
    assert view.file.reject_reason == "files/type-mismatch"
