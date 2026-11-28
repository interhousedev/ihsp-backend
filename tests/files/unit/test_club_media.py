"""The `club` scope and `club_media` purpose (club photos and videos)."""

from pathlib import Path
from uuid import uuid4

from app.modules.files.domain.errors import (
    FileTooLargeError,
    StoredFileNotFoundError,
    TypeNotAllowedError,
)
from app.modules.files.domain.policy import may_read, scope_for_purpose
from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileScope
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import PNG_BYTES, sha256_b64

import pytest

CLUB = FileScope.CLUB
MEDIA = FilePurpose.CLUB_MEDIA


def test_the_club_scope_and_purpose_have_stable_values(student: Actor) -> None:
    """The strings are stored in the database."""
    assert (CLUB.value, MEDIA.value) == ("club", "club_media")
    assert scope_for_purpose(MEDIA, student) == CLUB


async def test_club_media_is_refused_on_the_generic_route(
    fakes: FilesFakes, student: Actor
) -> None:
    """Only the activities module may start a club upload."""
    with pytest.raises(TypeNotAllowedError):
        await fakes.services.request_upload.execute(
            student,
            name="a.png",
            size=len(PNG_BYTES),
            content_type="image/png",
            sha256_b64=sha256_b64(PNG_BYTES),
            purpose=MEDIA,
        )
    assert fakes.db.all_rows() == []


async def test_a_club_upload_is_owned_by_the_club_and_never_expires(
    fakes: FilesFakes,
) -> None:
    """The key has no term; there is no expiry date and no per-actor quota."""
    club_id = uuid4()

    ticket = await fakes.services.request_upload.execute_for_owner(
        owner_id=club_id,
        scope=CLUB,
        purpose=MEDIA,
        name="Party.PNG",
        size=len(PNG_BYTES),
        content_type="image/png",
        sha256_b64=sha256_b64(PNG_BYTES),
        max_bytes=1000,
    )

    file = fakes.db.row(ticket.view.file.id)
    assert (file.scope, file.owner_id, file.expires_at) == (CLUB, club_id, None)
    assert file.key.startswith("club/2026-10/")
    assert file.key.endswith(".png")


async def test_a_club_upload_over_the_given_ceiling_is_refused(
    fakes: FilesFakes,
) -> None:
    """The caller passes the per-club limit as ``max_bytes``."""
    with pytest.raises(FileTooLargeError):
        await fakes.services.request_upload.execute_for_owner(
            owner_id=uuid4(),
            scope=CLUB,
            purpose=MEDIA,
            name="a.png",
            size=11,
            content_type="image/png",
            sha256_b64=sha256_b64(PNG_BYTES),
            max_bytes=10,
        )


async def test_a_non_media_name_is_refused_for_club_media(fakes: FilesFakes) -> None:
    """Club media takes photo and video formats only."""
    with pytest.raises(TypeNotAllowedError):
        await fakes.services.request_upload.execute_for_owner(
            owner_id=uuid4(),
            scope=CLUB,
            purpose=MEDIA,
            name="a.pdf",
            size=5,
            content_type="application/pdf",
            sha256_b64=sha256_b64(b"12345"),
            max_bytes=100,
        )


async def test_complete_club_verifies_the_object_and_refuses_other_scopes(
    fakes: FilesFakes,
) -> None:
    """``execute_club`` completes a pending club file; others look missing."""
    ticket = await fakes.services.request_upload.execute_for_owner(
        owner_id=uuid4(),
        scope=CLUB,
        purpose=MEDIA,
        name="a.png",
        size=len(PNG_BYTES),
        content_type="image/png",
        sha256_b64=sha256_b64(PNG_BYTES),
        max_bytes=1000,
    )
    fakes.storage.upload(ticket.upload, PNG_BYTES)

    view = await fakes.services.complete_upload.execute_club(ticket.view.file.id)

    assert view.file.status != FileStatus.PENDING.value
    with pytest.raises(StoredFileNotFoundError):
        await fakes.services.complete_upload.execute_club(uuid4())


async def test_the_club_scope_is_not_readable_by_the_uploader(
    fakes: FilesFakes, student: Actor
) -> None:
    """A club file belongs to the club id: only administrators read it directly."""
    ref = await fakes.services.public.store_bytes(
        owner_id=student.user_id,
        scope=CLUB,
        purpose=MEDIA,
        name="a.png",
        data=PNG_BYTES,
    )

    assert may_read(fakes.db.row(ref.id), student) is False


async def test_store_path_streams_a_file_from_disk(
    fakes: FilesFakes, tmp_path: Path
) -> None:
    """The video worker hands over a path; the file is hashed and stored."""
    path = tmp_path / "x.png"
    path.write_bytes(PNG_BYTES)
    club_id = uuid4()

    ref = await fakes.services.public.store_path(
        owner_id=club_id,
        scope=CLUB,
        purpose=MEDIA,
        name="x.png",
        path=str(path),
        content_type="image/png",
    )

    row = fakes.db.row(ref.id)
    assert (row.owner_id, row.expires_at, ref.byte_size) == (
        club_id,
        None,
        len(PNG_BYTES),
    )
    assert fakes.storage.objects[row.key].data == PNG_BYTES
