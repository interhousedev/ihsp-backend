"""SQL repository of links."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from app.modules.links.domain.errors import SlugTakenError
from app.modules.links.domain.link import LessonRole, Link, LinkKind, ShareMode
from app.modules.links.infrastructure.orm.link import Link as LinkRow
from app.modules.links.ports.link_repository import ModerationCursor

from sqlalchemy import ColumnElement, and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

SLUG_INDEX = "ix_links_slug_active"
SHARE_KINDS = (LinkKind.CHAT.value, LinkKind.FLASHCARD_SET.value)


def _to_entity(row: LinkRow) -> Link:
    return Link(
        id=row.id,
        slug=row.slug,
        kind=LinkKind(row.kind),
        owner_id=row.owner_id,
        created_at=row.created_at,
        target_url=row.target_url,
        file_id=row.file_id,
        target_id=row.target_id,
        title=row.title,
        lesson_id=row.lesson_id,
        lesson_role=LessonRole(row.lesson_role) if row.lesson_role else None,
        share_mode=ShareMode(row.share_mode) if row.share_mode else None,
        snapshot_seq=row.snapshot_seq,
        expires_at=row.expires_at,
        hits=row.hits,
        last_hit_at=row.last_hit_at,
        hidden_at=row.hidden_at,
        hidden_by=row.hidden_by,
        disabled_at=row.disabled_at,
        disabled_by=row.disabled_by,
        disabled_reason=row.disabled_reason,
        revoked_at=row.revoked_at,
        reports=row.reports,
        last_reported_at=row.last_reported_at,
        reports_reviewed_at=row.reports_reviewed_at,
        slug_released_at=row.slug_released_at,
    )


def _apply(row: LinkRow, link: Link) -> None:
    row.slug = link.slug
    row.kind = link.kind.value
    row.owner_id = link.owner_id
    row.target_url = link.target_url
    row.file_id = link.file_id
    row.target_id = link.target_id
    row.title = link.title
    row.lesson_id = link.lesson_id
    row.lesson_role = link.lesson_role.value if link.lesson_role else None
    row.share_mode = link.share_mode.value if link.share_mode else None
    row.snapshot_seq = link.snapshot_seq
    row.expires_at = link.expires_at
    row.hits = link.hits
    row.last_hit_at = link.last_hit_at
    row.hidden_at = link.hidden_at
    row.hidden_by = link.hidden_by
    row.disabled_at = link.disabled_at
    row.disabled_by = link.disabled_by
    row.disabled_reason = link.disabled_reason
    row.revoked_at = link.revoked_at
    row.reports = link.reports
    row.last_reported_at = link.last_reported_at
    row.reports_reviewed_at = link.reports_reviewed_at
    row.slug_released_at = link.slug_released_at


def _before(after: ModerationCursor) -> ColumnElement[bool]:
    """Rows that come after the cursor in (reports, last_reported_at, id) DESC order."""
    return or_(
        LinkRow.reports < after.reports,
        and_(
            LinkRow.reports == after.reports,
            or_(
                LinkRow.last_reported_at < after.last_reported_at,
                and_(
                    LinkRow.last_reported_at == after.last_reported_at,
                    LinkRow.id < after.link_id,
                ),
            ),
        ),
    )


class SqlLinkRepository:
    """Stores links in schema `links`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, link: Link) -> None:
        """Insert; a taken slug raises SlugTakenError and keeps the transaction."""
        row = LinkRow(
            id=link.id, created_at=link.created_at, updated_at=link.created_at
        )
        _apply(row, link)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as error:
            if SLUG_INDEX in str(error.orig):
                raise SlugTakenError(link.slug) from error
            raise

    async def get(self, link_id: UUID) -> Link | None:
        """Return the link or None."""
        row = await self.session.get(LinkRow, link_id)
        return _to_entity(row) if row else None

    async def get_by_slug(self, slug: str) -> Link | None:
        """Return the link that holds the slug now."""
        stmt = select(LinkRow).where(
            LinkRow.slug == slug, LinkRow.slug_released_at.is_(None)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def save(self, link: Link) -> None:
        """Write the link's fields back to its row."""
        row = await self.session.get(LinkRow, link.id)
        if row is None:
            raise LookupError(f"link {link.id} does not exist")
        _apply(row, link)
        await self.session.flush()

    async def list_by_owner(
        self,
        owner_id: UUID,
        *,
        kind: LinkKind | None,
        target_id: UUID | None,
        before_id: UUID | None,
        limit: int,
    ) -> list[Link]:
        """Return the owner's links newest first; deleted short links are hidden."""
        stmt = select(LinkRow).where(
            LinkRow.owner_id == owner_id,
            or_(LinkRow.revoked_at.is_(None), LinkRow.kind.in_(SHARE_KINDS)),
        )
        if kind is not None:
            stmt = stmt.where(LinkRow.kind == kind.value)
        if target_id is not None:
            stmt = stmt.where(LinkRow.target_id == target_id)
        if before_id is not None:
            stmt = stmt.where(LinkRow.id < before_id)
        stmt = stmt.order_by(LinkRow.id.desc()).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def list_for_lessons(self, lesson_ids: Sequence[UUID]) -> list[Link]:
        """Return live lesson resources, oldest first."""
        if not lesson_ids:
            return []
        stmt = (
            select(LinkRow)
            .where(LinkRow.lesson_id.in_(lesson_ids), LinkRow.revoked_at.is_(None))
            .order_by(LinkRow.created_at, LinkRow.id)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def lesson_urls_of_owner(
        self, owner_id: UUID, lesson_ids: Sequence[UUID]
    ) -> set[tuple[UUID, str]]:
        """Return (lesson id, URL) of all the owner's resources, deleted ones too."""
        if not lesson_ids:
            return set()
        stmt = select(LinkRow.lesson_id, LinkRow.target_url).where(
            LinkRow.owner_id == owner_id,
            LinkRow.lesson_id.in_(lesson_ids),
            LinkRow.target_url.is_not(None),
        )
        return {(row[0], row[1]) for row in (await self.session.execute(stmt)).all()}

    async def moderation_queue(
        self, *, after: ModerationCursor | None, limit: int
    ) -> list[Link]:
        """Return reported links not reviewed since the last report."""
        stmt = select(LinkRow).where(
            LinkRow.reports > 0,
            or_(
                LinkRow.reports_reviewed_at.is_(None),
                LinkRow.reports_reviewed_at < LinkRow.last_reported_at,
            ),
        )
        if after is not None:
            stmt = stmt.where(_before(after))
        stmt = stmt.order_by(
            LinkRow.reports.desc(), LinkRow.last_reported_at.desc(), LinkRow.id.desc()
        ).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def list_by_owners(self, owner_ids: Sequence[UUID], limit: int) -> list[Link]:
        """Return the newest links of the given owners."""
        if not owner_ids:
            return []
        stmt = (
            select(LinkRow)
            .where(LinkRow.owner_id.in_(owner_ids))
            .order_by(LinkRow.id.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def active_by_owner(self, owner_id: UUID) -> list[Link]:
        """Return the owner's links that are not revoked."""
        stmt = select(LinkRow).where(
            LinkRow.owner_id == owner_id, LinkRow.revoked_at.is_(None)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def active_by_files(self, file_ids: Sequence[UUID]) -> list[Link]:
        """Return links that are not revoked and point at one of the files."""
        if not file_ids:
            return []
        stmt = select(LinkRow).where(
            LinkRow.file_id.in_(file_ids), LinkRow.revoked_at.is_(None)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def active_by_target(self, kind: LinkKind, target_id: UUID) -> list[Link]:
        """Return the not revoked links of a kind that share the target."""
        stmt = select(LinkRow).where(
            LinkRow.kind == kind.value,
            LinkRow.target_id == target_id,
            LinkRow.revoked_at.is_(None),
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def release_revoked_before(self, cutoff: datetime, now: datetime) -> int:
        """Free the slugs of links revoked before the cutoff."""
        stmt = (
            update(LinkRow)
            .where(LinkRow.revoked_at < cutoff, LinkRow.slug_released_at.is_(None))
            .values(slug_released_at=now)
        )
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def add_hits(self, counts: Mapping[UUID, int], now: datetime) -> None:
        """Add click counts and set the last hit time."""
        for link_id, count in counts.items():
            stmt = (
                update(LinkRow)
                .where(LinkRow.id == link_id)
                .values(hits=LinkRow.hits + count, last_hit_at=now)
            )
            await self.session.execute(stmt)
