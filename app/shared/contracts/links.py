"""Links contracts (provider: links module)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class ResourceRef:
    """A link or file attached to a lesson."""

    link_id: UUID
    lesson_id: UUID
    role: Literal["material", "attachment", "homework"]
    kind: Literal["url", "file"]
    short_url: str
    title: str
    author_id: UUID
    author_first_name: str
    hidden: bool
    file_id: UUID | None


class LinksApi(Protocol):
    """Lesson resources for other modules."""

    async def lesson_resources(
        self, lesson_id: UUID, *, include_hidden: bool = False
    ) -> list[ResourceRef]:
        """Return the lesson's resources."""
        ...

    async def resources_for_lessons(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[ResourceRef]]:
        """Return resources grouped by lesson."""
        ...

    async def add_lesson_resource(
        self,
        actor: Actor,
        lesson_id: UUID,
        *,
        role: Literal["material", "attachment"],
        url: str | None = None,
        file_id: UUID | None = None,
    ) -> ResourceRef:
        """Attach a URL or an uploaded file to the lesson."""
        ...

    async def resolve_share(self, slug: str) -> tuple[str, UUID] | None:
        """Return (kind, target_id) of an active share link, else None."""
        ...
