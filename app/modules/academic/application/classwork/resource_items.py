"""Builds ``ResourceItem`` JSON from the lesson resources of the links module."""

from collections.abc import Sequence
from typing import Any

from app.modules.academic.application.classwork.people import PeopleDirectory, Person
from app.shared.contracts.links import ResourceRef


def resource_item(ref: ResourceRef, author: Person | None) -> dict[str, Any]:
    """Build one ``ResourceItem``.

    ``file`` is the stored file in the ``FileItem`` shape (null for a web address);
    students get the author's first name only.
    """
    person = (
        author.to_json()
        if author is not None
        else {
            "id": str(ref.author_id),
            "first_name": ref.author_first_name,
            "last_name": "",
        }
    )
    return {
        "link_id": str(ref.link_id),
        "lesson_id": str(ref.lesson_id),
        "role": ref.role,
        "kind": ref.kind,
        "short_url": ref.short_url,
        "title": ref.title,
        "author": person,
        "hidden": ref.hidden,
        "source": ref.source,
        "file": file_item(ref),
        "created_at": ref.created_at.isoformat() if ref.created_at else None,
    }


def file_item(ref: ResourceRef) -> dict[str, Any] | None:
    """The file of a resource as a ``FileItem``, or None for a web address."""
    file = ref.file
    if file is None:
        return None
    return {
        "id": str(file.id),
        "name": file.name,
        "content_type": file.content_type,
        "byte_size": file.byte_size,
        "purpose": file.purpose.value,
        "status": file.status,
        "reject_reason": None,
        "text_bytes": file.text_bytes,
        "assistant_ready": file.status == "ready" and file.text_bytes is not None,
        "created_at": ref.created_at.isoformat() if ref.created_at else None,
        "expires_on": None,
        "used_by": [{"kind": "lesson", "id": str(ref.lesson_id), "label": ref.title}],
    }


def student_resource_items(refs: Sequence[ResourceRef]) -> list[dict[str, Any]]:
    """Items as students see them: first names of authors only."""
    return [resource_item(ref, None) for ref in refs]


async def staff_resource_items(
    refs: Sequence[ResourceRef], people: PeopleDirectory
) -> list[dict[str, Any]]:
    """Items as staff see them: full names of authors."""
    authors = await people.people(ref.author_id for ref in refs)
    return [resource_item(ref, authors.get(ref.author_id)) for ref in refs]
