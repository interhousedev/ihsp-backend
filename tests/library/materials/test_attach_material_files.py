"""LIB-13: attaching a PDF, photos or Office files to a draft material."""

import dataclasses
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import FileFormat, ItemStatus, TextStatus
from app.modules.library.domain.errors import (
    FileTooLargeError,
    ItemNotFoundError,
    NotEditableError,
    TooManyPagesError,
)
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.contracts.files import FilePurpose
from app.shared.ids import new_id
from tests.fakes.library.material_files import (
    DOCX,
    JPEG,
    PNG,
    PPTX,
    MaterialFilesApi,
)
from tests.fakes.tasks import FakeTaskKicker
from tests.library.materials.helpers import ident

import pytest

MB = 1024 * 1024
LoadItem = Callable[[UUID | None], Awaitable[Item]]


@pytest.fixture
async def draft_id(
    library: LibraryServices, student: Actor, material_data: MaterialData
) -> UUID:
    """A draft of the student."""
    view = await library.materials.create_material.execute(
        student, material_data, locale="en"
    )
    return ident(view)


async def test_a_pdf_becomes_the_primary_file(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
    kicker: FakeTaskKicker,
    load_item: LoadItem,
) -> None:
    """LIB-13: one PDF; pages are counted, the scan job is started after commit."""
    pdf = files_api.upload(student.user_id, pages=7, byte_size=2 * MB)

    view = await library.materials.attach_material_files.execute(
        student, draft_id, [pdf], locale="en"
    )

    item = await load_item(draft_id)
    (item_file,) = item.files
    assert (item_file.file_id, item_file.format) == (pdf, FileFormat.PDF)
    assert item_file.is_primary is True
    assert item_file.pages == 7
    assert item_file.byte_size == 2 * MB
    assert item_file.readable is True
    assert item_file.text_status is TextStatus.PENDING
    assert item.page_count == 7
    assert item.status is ItemStatus.DRAFT
    assert [f.id for f in view.files] == [pdf]
    assert kicker.calls == [
        (
            "library.process_item_file",
            {"item_id": str(draft_id), "file_id": str(pdf)},
        )
    ]


async def test_photos_are_combined_into_one_pdf(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
    load_item: LoadItem,
) -> None:
    """LIB-13: up to 20 photos become one PDF; the photos are deleted afterwards."""
    photos = [
        files_api.upload(student.user_id, name=f"{i}.jpg", content_type=JPEG, pages=0)
        for i in range(3)
    ]

    await library.materials.attach_material_files.execute(
        student, draft_id, photos, locale="en"
    )

    item = await load_item(draft_id)
    (item_file,) = item.files
    assert files_api.combined == [tuple(photos)]
    assert item_file.file_id not in photos
    assert item_file.format is FileFormat.PDF
    assert item_file.pages == 3
    assert set(files_api.deleted) == set(photos)


async def test_more_than_twenty_photos_are_refused(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
) -> None:
    """LIB-13: 20 photos is the largest set."""
    photos = [
        files_api.upload(student.user_id, content_type=PNG, pages=0) for _ in range(21)
    ]

    with pytest.raises(TooManyPagesError):
        await library.materials.attach_material_files.execute(
            student, draft_id, photos, locale="en"
        )


async def test_a_student_pdf_over_sixty_pages_is_refused(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
) -> None:
    """LIB-13: students are limited to 60 pages."""
    pdf = files_api.upload(student.user_id, pages=61)

    with pytest.raises(TooManyPagesError) as caught:
        await library.materials.attach_material_files.execute(
            student, draft_id, [pdf], locale="en"
        )

    assert caught.value.params["max"] == 60


async def test_a_student_file_over_twenty_megabytes_is_refused(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
) -> None:
    """LIB-13: 20 MB is the student limit."""
    pdf = files_api.upload(student.user_id, byte_size=20 * MB + 1)

    with pytest.raises(FileTooLargeError) as caught:
        await library.materials.attach_material_files.execute(
            student, draft_id, [pdf], locale="en"
        )

    assert caught.value.params["max_mb"] == 20


async def test_a_teacher_may_attach_a_big_pdf_with_many_pages(
    library: LibraryServices,
    teacher: Actor,
    material_data: MaterialData,
    files_api: MaterialFilesApi,
    load_item: LoadItem,
) -> None:
    """LIB-13: teachers have 100 MB and no page limit."""
    view = await library.materials.create_material.execute(
        teacher, material_data, locale="en"
    )
    pdf = files_api.upload(teacher.user_id, pages=300, byte_size=90 * MB)

    await library.materials.attach_material_files.execute(
        teacher, ident(view), [pdf], locale="en"
    )

    assert (await load_item(view.card.id)).page_count == 300


async def test_a_teacher_file_over_one_hundred_megabytes_is_refused(
    library: LibraryServices,
    teacher: Actor,
    material_data: MaterialData,
    files_api: MaterialFilesApi,
) -> None:
    """LIB-13: 100 MB is the teacher limit."""
    view = await library.materials.create_material.execute(
        teacher, material_data, locale="en"
    )
    pdf = files_api.upload(teacher.user_id, byte_size=100 * MB + 1)

    with pytest.raises(FileTooLargeError):
        await library.materials.attach_material_files.execute(
            teacher, ident(view), [pdf], locale="en"
        )


async def test_a_teacher_adds_office_files_as_downloads(
    library: LibraryServices,
    teacher: Actor,
    material_data: MaterialData,
    files_api: MaterialFilesApi,
    load_item: LoadItem,
) -> None:
    """LIB-13: DOCX and PPTX are offered for download, not read in the browser."""
    view = await library.materials.create_material.execute(
        teacher, material_data, locale="en"
    )
    pdf = files_api.upload(teacher.user_id)
    slides = files_api.upload(teacher.user_id, name="s.pptx", content_type=PPTX)
    doc = files_api.upload(teacher.user_id, name="d.docx", content_type=DOCX)

    await library.materials.attach_material_files.execute(
        teacher, ident(view), [slides, pdf, doc], locale="en"
    )

    item = await load_item(view.card.id)
    by_id = {f.file_id: f for f in item.files}
    assert by_id[pdf].is_primary and by_id[pdf].readable
    assert not by_id[slides].is_primary and not by_id[slides].readable
    assert by_id[slides].format is FileFormat.PPTX
    assert by_id[doc].format is FileFormat.DOCX
    assert by_id[doc].text_status is TextStatus.NONE


async def test_a_student_cannot_attach_office_files(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
) -> None:
    """LIB-13: only teachers (and staff) may attach DOCX and PPTX."""
    doc = files_api.upload(student.user_id, content_type=DOCX)

    with pytest.raises(ValidationFailedError) as caught:
        await library.materials.attach_material_files.execute(
            student, draft_id, [doc], locale="en"
        )

    assert caught.value.params == {"field": "file_ids"}


@pytest.mark.parametrize("problem", ["unknown", "not mine", "wrong purpose", "empty"])
async def test_only_own_ready_uploads_of_the_right_purpose_are_accepted(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
    problem: str,
) -> None:
    """LIB-13: file ids come from the client, so they are checked."""
    ids: list[UUID] = []
    if problem == "unknown":
        ids = [new_id()]
    elif problem == "not mine":
        ids = [files_api.upload(other_student.user_id)]
    elif problem == "wrong purpose":
        ids = [files_api.upload(student.user_id, purpose=FilePurpose.AI_UPLOAD)]

    with pytest.raises(ValidationFailedError) as caught:
        await library.materials.attach_material_files.execute(
            student, draft_id, ids, locale="en"
        )

    assert caught.value.params == {"field": "file_ids"}


async def test_two_pdfs_or_pdf_with_photos_are_refused(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
) -> None:
    """LIB-13: one document per material: a single PDF or a set of photos."""
    first = files_api.upload(student.user_id)
    second = files_api.upload(student.user_id)
    photo = files_api.upload(student.user_id, content_type=JPEG, pages=0)

    for ids in ([first, second], [first, photo]):
        with pytest.raises(ValidationFailedError):
            await library.materials.attach_material_files.execute(
                student, draft_id, ids, locale="en"
            )


async def test_attaching_again_replaces_the_uploaded_file(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
    load_item: LoadItem,
) -> None:
    """LIB-13: a new upload replaces the old one, which is deleted after commit."""
    first = files_api.upload(student.user_id)
    second = files_api.upload(student.user_id, pages=5)
    await library.materials.attach_material_files.execute(
        student, draft_id, [first], locale="en"
    )

    await library.materials.attach_material_files.execute(
        student, draft_id, [second], locale="en"
    )

    item = await load_item(draft_id)
    assert [f.file_id for f in item.files] == [second]
    assert files_api.deleted == [first]


async def test_a_markdown_body_stays_next_to_an_uploaded_pdf(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    files_api: MaterialFilesApi,
    load_item: LoadItem,
) -> None:
    """LIB-13: the written text is kept; the PDF becomes the primary file."""
    data = dataclasses.replace(material_data, body_md="# Notes")
    created = await library.materials.create_material.execute(
        student, data, locale="en"
    )
    pdf = files_api.upload(student.user_id)

    await library.materials.attach_material_files.execute(
        student, ident(created), [pdf], locale="en"
    )

    item = await load_item(created.card.id)
    by_format = {f.format: f for f in item.files}
    assert by_format[FileFormat.PDF].is_primary is True
    assert by_format[FileFormat.MD].is_primary is False
    assert item.has_text is True


async def test_changes_requested_material_can_get_a_new_file(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
    load_item: LoadItem,
    set_status: Callable[..., Awaitable[None]],
) -> None:
    """LIB-13: after a librarian asks for changes the file may be replaced."""
    await set_status(draft_id, ItemStatus.CHANGES_REQUESTED)
    pdf = files_api.upload(student.user_id)

    await library.materials.attach_material_files.execute(
        student, draft_id, [pdf], locale="en"
    )

    assert [f.file_id for f in (await load_item(draft_id)).files] == [pdf]


@pytest.mark.parametrize(
    "status",
    [
        ItemStatus.PENDING_REVIEW,
        ItemStatus.PUBLISHED,
        ItemStatus.HELD,
        ItemStatus.REJECTED,
        ItemStatus.UNPUBLISHED,
    ],
)
async def test_files_cannot_change_outside_draft_and_changes_requested(
    library: LibraryServices,
    student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
    set_status: Callable[..., Awaitable[None]],
    status: ItemStatus,
) -> None:
    """LIB-13: a version is the way to replace the file of a live material."""
    await set_status(draft_id, status)
    pdf = files_api.upload(student.user_id)

    with pytest.raises(NotEditableError):
        await library.materials.attach_material_files.execute(
            student, draft_id, [pdf], locale="en"
        )


async def test_somebody_elses_draft_is_not_found(
    library: LibraryServices,
    other_student: Actor,
    draft_id: UUID,
    files_api: MaterialFilesApi,
) -> None:
    """LIB-13: `404`, never `403`, for another person's draft."""
    pdf = files_api.upload(other_student.user_id)

    with pytest.raises(ItemNotFoundError):
        await library.materials.attach_material_files.execute(
            other_student, draft_id, [pdf], locale="en"
        )
