"""WebVTT caption uploads: `.vtt` only for `lms_captions`, header, size and role."""

from app.modules.files.domain.errors import FileTooLargeError, TypeNotAllowedError
from app.modules.files.domain.policy import is_webvtt
from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import upload_and_complete

import pytest

CAPTIONS = FilePurpose.LMS_CAPTIONS
VTT = b"WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n"


@pytest.mark.parametrize(
    ("head", "valid"),
    [
        (b"WEBVTT\n", True),
        (b"\xef\xbb\xbfWEBVTT - lesson\n", True),
        (b"WEBVTT", True),
        (b"WEBVTTX\n", False),
        (b"1\n00:00:00,000 --> 00:00:01,000\n", False),
        (b"", False),
    ],
)
def test_the_webvtt_signature(head: bytes, valid: bool) -> None:
    """A BOM is allowed; `WEBVTT` must be followed by a space, a newline or the end."""
    assert is_webvtt(head) is valid


async def test_course_staff_upload_a_vtt(fakes: FilesFakes, teacher: Actor) -> None:
    """A `.vtt` with the header passes the checks."""
    view = await upload_and_complete(
        fakes,
        teacher,
        name="uz.vtt",
        data=VTT,
        content_type="text/vtt",
        purpose=CAPTIONS,
    )

    assert view.file.status != FileStatus.REJECTED
    assert view.file.purpose == CAPTIONS


async def test_a_vtt_without_the_header_is_rejected(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """An SRT renamed to `.vtt` fails the content check."""
    view = await upload_and_complete(
        fakes,
        teacher,
        name="uz.vtt",
        data=b"1\n00:00:00,000 --> 00:00:01,000\nHello\n",
        content_type="text/vtt",
        purpose=CAPTIONS,
    )

    assert view.file.status == FileStatus.REJECTED
    assert view.file.reject_reason == "files/type-mismatch"


async def test_a_vtt_over_one_mib_is_too_large(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """Caption tracks are capped at 1 MiB."""
    with pytest.raises(FileTooLargeError):
        await upload_and_complete(
            fakes,
            teacher,
            name="uz.vtt",
            data=VTT + b"x" * (1024 * 1024),
            content_type="text/vtt",
            purpose=CAPTIONS,
        )


async def test_students_cannot_upload_captions(
    fakes: FilesFakes, student: Actor
) -> None:
    """Only course staff roles may."""
    with pytest.raises(ForbiddenError):
        await upload_and_complete(
            fakes,
            student,
            name="uz.vtt",
            data=VTT,
            content_type="text/vtt",
            purpose=CAPTIONS,
        )


async def test_a_vtt_is_refused_for_other_purposes(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """Caption tracks only under `lms_captions`."""
    with pytest.raises(TypeNotAllowedError):
        await upload_and_complete(
            fakes,
            teacher,
            name="uz.vtt",
            data=VTT,
            content_type="text/vtt",
            purpose=FilePurpose.LINK,
        )


async def test_the_captions_purpose_takes_only_vtt(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """A PDF cannot hide behind `lms_captions`."""
    with pytest.raises(TypeNotAllowedError):
        await upload_and_complete(
            fakes,
            teacher,
            name="a.pdf",
            data=b"%PDF-1.4",
            content_type="application/pdf",
            purpose=CAPTIONS,
        )
