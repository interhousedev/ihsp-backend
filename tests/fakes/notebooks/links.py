"""LinksApi.lesson_resources for the notebooks tests."""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from app.shared.contracts.links import ResourceRef
from app.shared.ids import new_id
from tests.fakes.ai.contracts import FakeLinks


def make_resource(
    lesson_id: UUID,
    *,
    title: str = "Worksheet",
    file_id: UUID | None = None,
    role: Literal["material", "attachment", "homework"] = "material",
    hidden: bool = False,
    author_id: UUID | None = None,
    author_first_name: str = "Teacher",
) -> ResourceRef:
    """A lesson resource: a file when ``file_id`` is given, else a link."""
    link_id = new_id()
    return ResourceRef(
        link_id=link_id,
        lesson_id=lesson_id,
        role=role,
        kind="file" if file_id is not None else "url",
        short_url=f"https://go.test/{str(link_id)[:8]}",
        title=title,
        author_id=author_id or new_id(),
        author_first_name=author_first_name,
        hidden=hidden,
        file_id=file_id,
    )


class FakeLessonLinks(FakeLinks):
    """Resources of lessons; hidden ones are left out unless asked for."""

    def add(self, resource: ResourceRef) -> ResourceRef:
        """Attach a resource to its lesson."""
        self.items.setdefault(resource.lesson_id, []).append(resource)
        return resource

    async def lesson_resources(
        self, lesson_id: UUID, *, include_hidden: bool = False
    ) -> list[ResourceRef]:
        """Return the lesson's visible resources."""
        return [
            r for r in self.items.get(lesson_id, []) if include_hidden or not r.hidden
        ]

    async def resources_for_lessons(
        self, lesson_ids: Sequence[UUID], *, include_hidden: bool = False
    ) -> dict[UUID, list[ResourceRef]]:
        """Return the visible resources of the lessons, grouped by lesson."""
        return {
            lesson_id: await self.lesson_resources(
                lesson_id, include_hidden=include_hidden
            )
            for lesson_id in lesson_ids
        }
