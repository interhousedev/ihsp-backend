"""Fake links API: lesson resources."""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from app.shared.actor import Actor
from app.shared.contracts.links import ResourceRef
from app.shared.ids import new_id


class FakeLinks:
    """In-memory LinksApi keyed by lesson."""

    def __init__(self) -> None:
        """Start without resources."""
        self.resources: dict[UUID, list[ResourceRef]] = {}

    def add(
        self,
        lesson_id: UUID,
        *,
        role: Literal["material", "attachment", "homework"] = "material",
        author_id: UUID | None = None,
        author_first_name: str = "Teacher",
        title: str = "Lecture 5.pdf",
        hidden: bool = False,
    ) -> ResourceRef:
        """Add a resource to a lesson."""
        ref = ResourceRef(
            link_id=new_id(),
            lesson_id=lesson_id,
            role=role,
            kind="url",
            short_url=f"http://s/{str(new_id())[:6]}",
            title=title,
            author_id=author_id or new_id(),
            author_first_name=author_first_name,
            hidden=hidden,
            file_id=None,
        )
        self.resources.setdefault(lesson_id, []).append(ref)
        return ref

    async def lesson_resources(
        self, lesson_id: UUID, *, include_hidden: bool = False
    ) -> list[ResourceRef]:
        """Return the lesson's resources, hiding hidden ones by default."""
        return [
            ref
            for ref in self.resources.get(lesson_id, [])
            if include_hidden or not ref.hidden
        ]

    async def resources_for_lessons(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[ResourceRef]]:
        """Return visible resources grouped by lesson."""
        return {
            lid: await self.lesson_resources(lid)
            for lid in lesson_ids
            if lid in self.resources
        }

    async def add_lesson_resource(
        self,
        actor: Actor,
        lesson_id: UUID,
        *,
        role: Literal["material", "attachment"],
        url: str | None = None,
        file_id: UUID | None = None,
    ) -> ResourceRef:
        """Add a resource on behalf of the actor."""
        return self.add(lesson_id, role=role, author_id=actor.user_id)
