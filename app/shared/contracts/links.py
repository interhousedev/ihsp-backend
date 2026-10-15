"""Links contracts (provider: links module)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor
from app.shared.contracts.files import FileRef


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
    # "emis": brought by EMIS (a hint, labelled in the UI), "user": added by a person.
    source: Literal["user", "emis"] = "user"
    # The stored file (name, type, size) and when the resource was added: the student
    # app shows the size and offers a preview for images, PDFs, video and audio.
    file: FileRef | None = None
    created_at: datetime | None = None


# Lesson resources that an outside system (EMIS) brought carry this author, who is no
# user account: the resource list shows the name "EMIS".
EMIS_AUTHOR_ID = UUID("00000000-0000-0000-0000-00000000e015")
EMIS_AUTHOR_NAME = "EMIS"


@dataclass(frozen=True, slots=True)
class ImportedUrl:
    """A web address an outside system attaches to a lesson as a material."""

    lesson_id: UUID
    url: str
    title: str


@dataclass(frozen=True, slots=True)
class ImportedFile:
    """A material an outside system linked, downloaded into a stored file."""

    lesson_id: UUID
    source_url: str  # the outside address: the re-sync key
    file_id: UUID


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

    async def import_lesson_urls(self, urls: Sequence[ImportedUrl]) -> int:
        """Attach URLs from EMIS as materials (author "EMIS"); return how many are new.

        Idempotent: a URL that EMIS already attached to the lesson is skipped, even
        if a teacher deleted it since. Blocked or malformed URLs are skipped.
        """
        ...

    async def emis_sources(self, lesson_ids: Sequence[UUID]) -> set[tuple[UUID, str]]:
        """Return (lesson id, URL) of everything EMIS ever attached, deleted too."""
        ...

    async def import_lesson_files(self, files: Sequence[ImportedFile]) -> int:
        """Attach stored files as EMIS materials; return how many are new.

        Idempotent like ``import_lesson_urls``: a (lesson, source URL) EMIS already
        attached is skipped.
        """
        ...

    async def purge_emis_resources(self, lesson_ids: Sequence[UUID]) -> list[UUID]:
        """Delete every EMIS resource of the lessons for good; return their file ids.

        Only resources whose author is EMIS go; people's uploads stay.
        """
        ...

    async def resolve_share(self, slug: str) -> tuple[str, UUID] | None:
        """Return (kind, target_id) of an active share link, else None."""
        ...
