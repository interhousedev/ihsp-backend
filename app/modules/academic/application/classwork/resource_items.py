"""Builds ``ResourceItem`` JSON from the lesson resources of the links module."""

from collections.abc import Sequence
from typing import Any

from app.modules.academic.application.classwork.people import PeopleDirectory, Person
from app.shared.contracts.links import ResourceRef


def resource_item(ref: ResourceRef, author: Person | None) -> dict[str, Any]:
    """Build one ``ResourceItem``.

    The links contract carries no file details and no creation time, so ``file``
    and ``created_at`` are null; students get the author's first name only.
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
        "file": None,
        "created_at": None,
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
