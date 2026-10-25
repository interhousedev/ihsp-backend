"""Persistence port for links."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.links.domain.link import Link, LinkKind


@dataclass(frozen=True, slots=True)
class ModerationCursor:
    """Position in the moderation queue (reports, last report, id), all descending."""

    reports: int
    last_reported_at: datetime
    link_id: UUID


class LinkRepository(Protocol):
    """Stores links; the unit of work owns the transaction."""

    async def add(self, link: Link) -> None:
        """Insert a link; raise SlugTakenError if the slug is already in use."""
        ...

    async def get(self, link_id: UUID) -> Link | None:
        """Return the link or None."""
        ...

    async def get_by_slug(self, slug: str) -> Link | None:
        """Return the link that holds the slug now (released slugs are free)."""
        ...

    async def save(self, link: Link) -> None:
        """Write the changed fields of the link."""
        ...

    async def list_by_owner(
        self,
        owner_id: UUID,
        *,
        kind: LinkKind | None,
        target_id: UUID | None,
        before_id: UUID | None,
        limit: int,
    ) -> list[Link]:
        """Return the owner's links, newest first, without deleted short links."""
        ...

    async def list_for_lessons(self, lesson_ids: Sequence[UUID]) -> list[Link]:
        """Return live lesson resources (hidden included), oldest first."""
        ...

    async def lesson_urls_of_owner(
        self, owner_id: UUID, lesson_ids: Sequence[UUID]
    ) -> set[tuple[UUID, str]]:
        """Return (lesson id, URL) of all the owner's resources, deleted ones too.

        For an imported file the URL is where it came from (``source_url``).
        """
        ...

    async def delete_owned_on_lessons(
        self, owner_id: UUID, lesson_ids: Sequence[UUID]
    ) -> list[Link]:
        """Delete the owner's resources on the lessons for good; return them."""
        ...

    async def moderation_queue(
        self, *, after: ModerationCursor | None, limit: int
    ) -> list[Link]:
        """Return reported links not reviewed since their last report."""
        ...

    async def list_by_owners(self, owner_ids: Sequence[UUID], limit: int) -> list[Link]:
        """Return the newest links of the given owners."""
        ...

    async def active_by_owner(self, owner_id: UUID) -> list[Link]:
        """Return the owner's links that are not revoked."""
        ...

    async def active_by_files(self, file_ids: Sequence[UUID]) -> list[Link]:
        """Return links that are not revoked and point at one of the files."""
        ...

    async def active_by_target(self, kind: LinkKind, target_id: UUID) -> list[Link]:
        """Return the not revoked links of a kind that share the target."""
        ...

    async def release_revoked_before(self, cutoff: datetime, now: datetime) -> int:
        """Free the slugs of links revoked before the cutoff; return how many."""
        ...

    async def add_hits(self, counts: Mapping[UUID, int], now: datetime) -> None:
        """Add click counts to the links and set last_hit_at."""
        ...

    async def hide_rules(
        self, teacher_ids: Sequence[UUID]
    ) -> set[tuple[UUID, UUID, UUID]]:
        """Return (teacher, subject, group) of the teachers' "hide EMIS" rules."""
        ...

    async def set_hide_rule(
        self,
        teacher_id: UUID,
        subject_id: UUID,
        group_id: UUID,
        *,
        on: bool,
        now: datetime,
    ) -> None:
        """Add (on) or remove the "hide EMIS sources" rule; idempotent."""
        ...
