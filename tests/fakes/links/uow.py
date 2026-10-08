"""In-memory unit of work and link repository with transaction semantics."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.links.domain.errors import SlugTakenError
from app.modules.links.domain.link import Link, LinkKind
from app.modules.links.ports.link_repository import ModerationCursor
from app.shared.db.uow import AfterCommit
from app.shared.notifications import AuditDraft, NotificationDraft


class LinkStore:
    """Committed state shared by every unit of work of one test."""

    def __init__(self) -> None:
        """Start with no links."""
        self.links: dict[UUID, Link] = {}
        self.audits: list[AuditDraft] = []
        self.notifications: list[NotificationDraft] = []
        self.commits = 0


class FakeLinkRepository:
    """Works on a copy of the store; the unit of work writes it back on commit."""

    def __init__(self, working: dict[UUID, Link]) -> None:
        """Bind to the working copy of one transaction."""
        self.working = working

    async def add(self, link: Link) -> None:
        """Insert a copy; a slug held by another unreleased link raises."""
        for other in self.working.values():
            if other.slug == link.slug and other.slug_released_at is None:
                raise SlugTakenError(link.slug)
        self.working[link.id] = replace(link)

    async def get(self, link_id: UUID) -> Link | None:
        """Return a copy of the link or None."""
        link = self.working.get(link_id)
        return replace(link) if link else None

    async def get_by_slug(self, slug: str) -> Link | None:
        """Return the link that holds the slug now."""
        for link in self.working.values():
            if link.slug == slug and link.slug_released_at is None:
                return replace(link)
        return None

    async def save(self, link: Link) -> None:
        """Replace the stored link with a copy."""
        if link.id not in self.working:
            raise LookupError(str(link.id))
        self.working[link.id] = replace(link)

    async def list_by_owner(
        self,
        owner_id: UUID,
        *,
        kind: LinkKind | None,
        target_id: UUID | None,
        before_id: UUID | None,
        limit: int,
    ) -> list[Link]:
        """Return the owner's links, newest first."""
        found = [
            link
            for link in self.working.values()
            if link.owner_id == owner_id
            and (link.revoked_at is None or link.is_share)
            and (kind is None or link.kind is kind)
            and (target_id is None or link.target_id == target_id)
            and (before_id is None or link.id < before_id)
        ]
        found.sort(key=lambda link: link.id, reverse=True)
        return [replace(link) for link in found[:limit]]

    async def list_for_lessons(self, lesson_ids: Sequence[UUID]) -> list[Link]:
        """Return live lesson resources, oldest first."""
        found = [
            link
            for link in self.working.values()
            if link.lesson_id in lesson_ids and link.revoked_at is None
        ]
        found.sort(key=lambda link: (link.created_at, link.id))
        return [replace(link) for link in found]

    async def moderation_queue(
        self, *, after: ModerationCursor | None, limit: int
    ) -> list[Link]:
        """Return reported links in (reports, last_reported_at, id) DESC order."""
        found = [link for link in self.working.values() if link.needs_review]
        found.sort(
            key=lambda link: (link.reports, link.last_reported_at, link.id),
            reverse=True,
        )
        if after is not None:
            cursor = (after.reports, after.last_reported_at, after.link_id)
            found = [
                link
                for link in found
                if (link.reports, link.last_reported_at, link.id) < cursor
            ]
        return [replace(link) for link in found[:limit]]

    async def list_by_owners(self, owner_ids: Sequence[UUID], limit: int) -> list[Link]:
        """Return the newest links of the owners."""
        found = [link for link in self.working.values() if link.owner_id in owner_ids]
        found.sort(key=lambda link: link.id, reverse=True)
        return [replace(link) for link in found[:limit]]

    async def active_by_owner(self, owner_id: UUID) -> list[Link]:
        """Return the owner's links that are not revoked."""
        return [
            replace(link)
            for link in self.working.values()
            if link.owner_id == owner_id and link.revoked_at is None
        ]

    async def release_revoked_before(self, cutoff: datetime, now: datetime) -> int:
        """Free the slugs of links revoked before the cutoff."""
        count = 0
        for link in self.working.values():
            if (
                link.revoked_at is not None
                and link.revoked_at < cutoff
                and link.slug_released_at is None
            ):
                link.slug_released_at = now
                count += 1
        return count

    async def add_hits(self, counts: Mapping[UUID, int], now: datetime) -> None:
        """Add click counts."""
        for link_id, count in counts.items():
            link = self.working[link_id]
            link.hits += count
            link.last_hit_at = now


class FakeLinksUnitOfWork:
    """One transaction over a LinkStore."""

    def __init__(self, store: LinkStore) -> None:
        """Remember the store; the transaction opens in __aenter__."""
        self.store = store
        self.committed = False
        self._working: dict[UUID, Link] = {}
        self._audits: list[AuditDraft] = []
        self._notifications: list[NotificationDraft] = []
        self._hooks: list[AfterCommit] = []
        self._repo = FakeLinkRepository(self._working)

    @property
    def links(self) -> FakeLinkRepository:
        """Return the repository of this transaction."""
        return self._repo

    async def __aenter__(self) -> Self:
        """Copy the committed state."""
        self._working = {key: replace(link) for key, link in self.store.links.items()}
        self._repo = FakeLinkRepository(self._working)
        self.committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Discard the working copy; commit() already wrote what should stay."""

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications."""
        self._notifications.extend(drafts)

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        self._audits.extend(drafts)

    def after_commit(self, hook: AfterCommit) -> None:
        """Run a hook after commit."""
        self._hooks.append(hook)

    async def commit(self) -> None:
        """Write the working copy back to the store."""
        self.store.links = {key: replace(link) for key, link in self._working.items()}
        self.store.audits.extend(self._audits)
        self.store.notifications.extend(self._notifications)
        self.store.commits += 1
        self.committed = True
        self._audits, self._notifications = [], []
        hooks, self._hooks = self._hooks, []
        for hook in hooks:
            await hook()


class FakeUowFactory:
    """Callable that opens a fresh unit of work on the shared store."""

    def __init__(self, store: LinkStore | None = None) -> None:
        """Create or reuse a store."""
        self.store = store or LinkStore()

    def __call__(self) -> FakeLinksUnitOfWork:
        """Return a new unit of work."""
        return FakeLinksUnitOfWork(self.store)
