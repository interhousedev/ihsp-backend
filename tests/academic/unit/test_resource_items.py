"""Lesson resources as students see them: the file details reach the student app."""

from datetime import UTC, datetime
from uuid import uuid4

from app.modules.academic.application.classwork.resource_items import (
    student_resource_items,
)
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.contracts.links import ResourceRef

ADDED = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)


def _ref(file: FileRef | None) -> ResourceRef:
    return ResourceRef(
        link_id=uuid4(),
        lesson_id=uuid4(),
        role="material",
        kind="file" if file else "url",
        short_url="https://s.ihsu.uz/abc",
        title="Worksheet",
        author_id=uuid4(),
        author_first_name="Nodira",
        hidden=False,
        file_id=file.id if file else None,
        file=file,
        created_at=ADDED,
    )


def test_a_file_resource_carries_its_name_type_size_and_date() -> None:
    file = FileRef(
        id=uuid4(),
        owner_id=uuid4(),
        scope=FileScope.STAFF,
        purpose=FilePurpose.LINK,
        name="worksheet.pdf",
        content_type="application/pdf",
        byte_size=2048,
        status="ready",
        text_bytes=None,
    )

    (item,) = student_resource_items([_ref(file)])

    assert item["file"]["id"] == str(file.id)
    assert item["file"]["content_type"] == "application/pdf"
    assert item["file"]["byte_size"] == 2048
    assert item["created_at"] == ADDED.isoformat()


def test_a_web_address_has_no_file() -> None:
    (item,) = student_resource_items([_ref(None)])

    assert item["file"] is None
    assert item["created_at"] == ADDED.isoformat()
