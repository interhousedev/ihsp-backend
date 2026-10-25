"""LIB-5 (files part): FilesApi.combine_images_to_pdf for photo uploads of materials."""

import io
from dataclasses import replace
from uuid import UUID, uuid4

from app.modules.files.domain.errors import (
    FileDeletedError,
    FileNotReadyError,
    FileTooLargeError,
    ImageCountError,
    ImageNotSupportedError,
    StoredFileNotFoundError,
    TypeNotAllowedError,
)
from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import DEFAULT_LIMITS, FilesFakes, build_files_fakes
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import (
    PDF_TYPE,
    make_jpeg,
    make_pdf,
    make_png,
    upload_and_complete,
    upload_ready,
)

import pytest
from pypdf import PdfReader

MATERIAL = FilePurpose.LIBRARY_MATERIAL


async def _photo(
    fakes: FilesFakes, owner: Actor, data: bytes, name: str = "photo.jpg"
) -> UUID:
    content_type = "image/png" if name.endswith(".png") else "image/jpeg"
    return await upload_ready(
        fakes, owner, name=name, data=data, content_type=content_type, purpose=MATERIAL
    )


async def _combine(
    fakes: FilesFakes, owner: Actor, ids: list[UUID], name: str = "Notes"
) -> FileRef:
    return await fakes.services.public.combine_images_to_pdf(
        ids,
        owner_id=owner.user_id,
        scope=FileScope.LIBRARY,
        purpose=MATERIAL,
        name=name,
    )


def _pages(fakes: FilesFakes, ref: FileRef) -> PdfReader:
    data = fakes.storage.objects[fakes.db.row(ref.id).key].data
    return PdfReader(io.BytesIO(data), strict=True)


async def test_photos_become_one_pdf_page_per_photo_in_the_given_order(
    fakes: FilesFakes, student: Actor
) -> None:
    """LIB-5: up to 20 images combined on the server."""
    wide = await _photo(fakes, student, make_jpeg(200, 100))
    tall = await _photo(fakes, student, make_png(100, 200), "scan.png")

    ref = await _combine(fakes, student, [tall, wide])

    pages = _pages(fakes, ref).pages
    assert [float(p.mediabox.height) for p in pages] == [1190.0, 297.5]


async def test_the_new_file_is_a_normal_library_file_of_the_owner(
    fakes: FilesFakes, student: Actor
) -> None:
    """Stored like any server-side file: library scope, processing, text job queued."""
    photo = await _photo(fakes, student, make_jpeg(20, 20))
    fakes.kicker.calls.clear()

    ref = await _combine(fakes, student, [photo])

    row = fakes.db.row(ref.id)
    assert (ref.scope, ref.purpose, ref.owner_id) == (
        FileScope.LIBRARY,
        MATERIAL,
        student.user_id,
    )
    assert ref.content_type == PDF_TYPE
    assert ref.status == FileStatus.PROCESSING.value
    assert row.key.startswith("library/2026-10/") and row.key.endswith(".pdf")
    assert fakes.kicker.calls == [("files.process", {"file_id": str(ref.id)})]


async def test_the_pdf_goes_through_the_normal_scan_and_has_a_page_count(
    fakes: FilesFakes, student: Actor
) -> None:
    """The library's scan job treats it like any uploaded PDF."""
    photos = [await _photo(fakes, student, make_jpeg(20, 20)) for _ in range(3)]
    ref = await _combine(fakes, student, photos)

    await fakes.services.process_file.execute(ref.id)

    assert await fakes.services.public.page_count(ref.id) == 3
    assert fakes.db.row(ref.id).status == FileStatus.READY


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("Notes", "Notes.pdf"),
        ("Notes.pdf", "Notes.pdf"),
        ("Notes.PDF", "Notes.PDF"),
        ("week 3.jpg", "week 3.jpg.pdf"),
        ("../../x", "x.pdf"),
    ],
)
async def test_the_name_always_ends_in_pdf(
    fakes: FilesFakes, student: Actor, given: str, stored: str
) -> None:
    """A caller that forgets the extension still gets a valid PDF file."""
    photo = await _photo(fakes, student, make_jpeg(20, 20))

    ref = await _combine(fakes, student, [photo], name=given)

    assert ref.name == stored


async def test_the_same_photo_may_appear_twice(
    fakes: FilesFakes, student: Actor
) -> None:
    """Two pages for a two-sided sheet scanned once, say."""
    photo = await _photo(fakes, student, make_jpeg(20, 20))

    ref = await _combine(fakes, student, [photo, photo])

    assert len(_pages(fakes, ref).pages) == 2


async def test_twenty_photos_are_the_most(fakes: FilesFakes, student: Actor) -> None:
    """LIB-5: more than 20 images are refused before anything is read."""
    photo = await _photo(fakes, student, make_jpeg(20, 20))

    ref = await _combine(fakes, student, [photo] * 20)
    with pytest.raises(ImageCountError) as caught:
        await _combine(fakes, student, [photo] * 21)

    assert len(_pages(fakes, ref).pages) == 20
    assert caught.value.params == {"max": 20}
    assert caught.value.status == 422


async def test_no_photos_is_refused(fakes: FilesFakes, student: Actor) -> None:
    """At least one."""
    with pytest.raises(ImageCountError):
        await _combine(fakes, student, [])


async def test_someone_elses_or_unknown_photos_are_not_found(
    fakes: FilesFakes, student: Actor, teacher: Actor
) -> None:
    """The owner check: files of other users do not exist for this call."""
    theirs = await _photo(fakes, teacher, make_jpeg(20, 20))
    mine = await _photo(fakes, student, make_jpeg(20, 20))

    with pytest.raises(StoredFileNotFoundError):
        await _combine(fakes, student, [mine, theirs])
    with pytest.raises(StoredFileNotFoundError):
        await _combine(fakes, student, [uuid4()])


async def test_a_deleted_or_unfinished_photo_is_refused(
    fakes: FilesFakes, student: Actor
) -> None:
    """Only uploaded, accepted files can be read."""
    gone = await _photo(fakes, student, make_jpeg(20, 20))
    async with fakes.db.uow() as uow:
        await uow.files.mark_deleted([gone], fakes.clock.now())
        await uow.commit()
    pending = (
        await fakes.services.request_upload.execute(
            student,
            name="p.jpg",
            size=10,
            content_type="image/jpeg",
            sha256_b64="A" * 43 + "=",
            purpose=MATERIAL,
        )
    ).view.file.id

    with pytest.raises(FileDeletedError):
        await _combine(fakes, student, [gone])
    with pytest.raises(FileNotReadyError):
        await _combine(fakes, student, [pending])


async def test_a_file_that_is_not_an_image_is_refused(
    fakes: FilesFakes, student: Actor
) -> None:
    """A PDF among the "photos"."""
    view = await upload_and_complete(
        fakes,
        student,
        name="doc.pdf",
        data=make_pdf("not a photo"),
        content_type=PDF_TYPE,
        purpose=MATERIAL,
    )

    with pytest.raises(ImageNotSupportedError):
        await _combine(fakes, student, [view.file.id])


async def test_a_photo_the_assembler_cannot_embed_is_refused_and_nothing_is_stored(
    fakes: FilesFakes, student: Actor
) -> None:
    """A PNG with an alpha channel: the message asks for a JPEG."""
    ok = await _photo(fakes, student, make_jpeg(20, 20))
    alpha = await _photo(fakes, student, make_png(8, 8, color_type=6), "shot.png")
    before = len(fakes.db.all_rows())

    with pytest.raises(ImageNotSupportedError) as caught:
        await _combine(fakes, student, [ok, alpha])

    assert caught.value.message_key == "error-file-image-unsupported"
    assert len(fakes.db.all_rows()) == before


async def test_photos_that_together_exceed_the_scope_limit_are_refused_unread(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """The result must fit the library ceiling; the check uses the stored sizes."""
    jpeg = make_jpeg(20, 20) + bytes(3000)  # bytes after the end are ignored
    limits = replace(DEFAULT_LIMITS, library_file_max_bytes=9000)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    ids = [await _photo(fakes, student, jpeg) for _ in range(3)]

    two = await _combine(fakes, student, ids[:2])
    with pytest.raises(FileTooLargeError):
        await _combine(fakes, student, ids)

    assert two.byte_size <= 9000


async def test_the_scope_and_purpose_pair_is_checked(
    fakes: FilesFakes, student: Actor
) -> None:
    """The combined PDF obeys the same rule as any stored file."""
    photo = await _photo(fakes, student, make_jpeg(20, 20))

    with pytest.raises(TypeNotAllowedError):
        await fakes.services.public.combine_images_to_pdf(
            [photo],
            owner_id=student.user_id,
            scope=FileScope.STUDENT,
            purpose=MATERIAL,
            name="x.pdf",
        )
