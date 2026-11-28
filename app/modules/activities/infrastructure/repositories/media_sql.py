"""SQL repositories of club albums and media."""

from __future__ import annotations

import builtins
from datetime import datetime
from uuid import UUID

from app.modules.activities.domain.media import (
    Album,
    AlbumVisibility,
    ClubMediaOverrides,
    HiddenSource,
    Media,
    MediaBlock,
    MediaKind,
    MediaReport,
    MediaStatus,
    MediaUsage,
    ReportStatus,
)
from app.modules.activities.infrastructure.orm import tables as t
from app.modules.activities.infrastructure.repositories.sql import (
    _dump,
    _load,
    _Repo,
)

from sqlalchemy import and_, exists, func, or_, select, update

_LIVE = (MediaStatus.DELETED.value, MediaStatus.FAILED.value)


def _album(r: t.AlbumRow) -> Album:
    return _load(Album, r, visibility=AlbumVisibility)


def _media(r: t.MediaRow) -> Media:
    return _load(
        Media,
        r,
        kind=MediaKind,
        usage=MediaUsage,
        status=MediaStatus,
        hidden_source=lambda v: HiddenSource(v) if v else None,
    )


def _report(r: t.MediaReportRow) -> MediaReport:
    return _load(MediaReport, r, status=ReportStatus)


class SqlAlbumRepository(_Repo):
    """Albums."""

    async def add(self, album: Album) -> None:
        """Insert."""
        await self.save(album)

    async def save(self, album: Album) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.AlbumRow, album))

    async def get(self, album_id: UUID) -> Album | None:
        """One album, deleted or not."""
        row = await self._s.get(t.AlbumRow, album_id)
        return _album(row) if row else None

    async def get_by_source_ref(self, source_ref: str) -> Album | None:
        """The album an import created."""
        row = await self._s.scalar(
            select(t.AlbumRow).where(t.AlbumRow.source_ref == source_ref)
        )
        return _album(row) if row else None

    async def root_for_event(self, event_id: UUID) -> Album | None:
        """The live root album of an event."""
        row = await self._s.scalar(
            select(t.AlbumRow).where(
                t.AlbumRow.event_id == event_id, t.AlbumRow.deleted_at.is_(None)
            )
        )
        return _album(row) if row else None

    async def list_children(
        self, club_id: UUID, parent_id: UUID | None
    ) -> builtins.list[Album]:
        """Live albums under a parent, newest event date first."""
        cond = (
            t.AlbumRow.parent_id.is_(None)
            if parent_id is None
            else t.AlbumRow.parent_id == parent_id
        )
        rows = await self._s.scalars(
            select(t.AlbumRow)
            .where(t.AlbumRow.club_id == club_id, t.AlbumRow.deleted_at.is_(None), cond)
            .order_by(
                t.AlbumRow.event_date.desc().nulls_last(), t.AlbumRow.created_at.desc()
            )
        )
        return [_album(r) for r in rows]

    async def item_counts(
        self, album_ids: builtins.list[UUID]
    ) -> dict[UUID, tuple[int, int]]:
        """``(ready items, live folders)`` per album."""
        if not album_ids:
            return {}
        items = dict(
            (
                await self._s.execute(
                    select(t.MediaRow.album_id, func.count())
                    .where(
                        t.MediaRow.album_id.in_(album_ids),
                        t.MediaRow.status == MediaStatus.READY.value,
                    )
                    .group_by(t.MediaRow.album_id)
                )
            ).tuples()
        )
        folders = dict(
            (
                await self._s.execute(
                    select(t.AlbumRow.parent_id, func.count())
                    .where(
                        t.AlbumRow.parent_id.in_(album_ids),
                        t.AlbumRow.deleted_at.is_(None),
                    )
                    .group_by(t.AlbumRow.parent_id)
                )
            ).tuples()
        )
        return {a: (items.get(a, 0), folders.get(a, 0)) for a in album_ids}


class SqlMediaRepository(_Repo):
    """Media items, reports, blocks and per-club limit overrides."""

    async def add(self, media: Media) -> None:
        """Insert."""
        await self.save(media)

    async def save(self, media: Media) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.MediaRow, media))

    async def remove(self, media_id: UUID) -> None:
        """Delete the row for good."""
        row = await self._s.get(t.MediaRow, media_id)
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()

    async def get(self, media_id: UUID) -> Media | None:
        """One item."""
        row = await self._s.get(t.MediaRow, media_id)
        return _media(row) if row else None

    async def get_many(self, media_ids: builtins.list[UUID]) -> builtins.list[Media]:
        """Items by id."""
        if not media_ids:
            return []
        rows = await self._s.scalars(
            select(t.MediaRow).where(t.MediaRow.id.in_(media_ids))
        )
        return [_media(r) for r in rows]

    async def get_by_source_ref(self, source_ref: str) -> Media | None:
        """The item an import created."""
        row = await self._s.scalar(
            select(t.MediaRow).where(t.MediaRow.source_ref == source_ref)
        )
        return _media(row) if row else None

    async def find_duplicate(self, album_id: UUID, sha256: str) -> Media | None:
        """A non-deleted item of the album with the same content."""
        row = await self._s.scalar(
            select(t.MediaRow).where(
                t.MediaRow.album_id == album_id,
                t.MediaRow.content_sha256 == sha256,
                t.MediaRow.status != MediaStatus.DELETED.value,
            )
        )
        return _media(row) if row else None

    async def list_album(
        self,
        album_id: UUID,
        *,
        statuses: frozenset[MediaStatus],
        kind: MediaKind | None,
        after: tuple[int, UUID] | None,
        limit: int,
    ) -> builtins.list[Media]:
        """Items ordered by ``(position, id)`` after the cursor."""
        q = select(t.MediaRow).where(
            t.MediaRow.album_id == album_id,
            t.MediaRow.status.in_([s.value for s in statuses]),
        )
        if kind is not None:
            q = q.where(t.MediaRow.kind == kind.value)
        if after is not None:
            pos, mid = after
            q = q.where(
                or_(
                    t.MediaRow.position > pos,
                    and_(t.MediaRow.position == pos, t.MediaRow.id > mid),
                )
            )
        rows = await self._s.scalars(
            q.order_by(t.MediaRow.position, t.MediaRow.id).limit(limit)
        )
        return [_media(r) for r in rows]

    async def list_for_announcement(
        self, announcement_id: UUID
    ) -> builtins.list[Media]:
        """Photos of an announcement."""
        rows = await self._s.scalars(
            select(t.MediaRow)
            .where(
                t.MediaRow.announcement_id == announcement_id,
                t.MediaRow.status != MediaStatus.DELETED.value,
            )
            .order_by(t.MediaRow.position, t.MediaRow.id)
        )
        return [_media(r) for r in rows]

    async def count_album(self, album_id: UUID) -> int:
        """Items that are not deleted or failed."""
        n = await self._s.scalar(
            select(func.count())
            .select_from(t.MediaRow)
            .where(t.MediaRow.album_id == album_id, t.MediaRow.status.not_in(_LIVE))
        )
        return int(n or 0)

    async def next_position(self, album_id: UUID) -> int:
        """One past the highest position."""
        top = await self._s.scalar(
            select(func.max(t.MediaRow.position)).where(t.MediaRow.album_id == album_id)
        )
        return 0 if top is None else int(top) + 1

    async def used_bytes(self, club_id: UUID) -> int:
        """Bytes of the club's items that are not deleted."""
        n = await self._s.scalar(
            select(func.coalesce(func.sum(t.MediaRow.byte_size), 0)).where(
                t.MediaRow.club_id == club_id,
                t.MediaRow.status != MediaStatus.DELETED.value,
            )
        )
        return int(n or 0)

    async def used_bytes_locked(self, club_id: UUID) -> int:
        """``used_bytes`` after locking the club row until the transaction ends.

        Quota check and reservation of concurrent uploads and restores of one
        club run one after another, so two of them cannot both fit the last bytes.
        """
        await self._s.execute(
            select(t.ClubRow.id).where(t.ClubRow.id == club_id).with_for_update()
        )
        return await self.used_bytes(club_id)

    async def item_count(self, club_id: UUID) -> int:
        """The club's items that are not deleted."""
        n = await self._s.scalar(
            select(func.count())
            .select_from(t.MediaRow)
            .where(
                t.MediaRow.club_id == club_id,
                t.MediaRow.status != MediaStatus.DELETED.value,
            )
        )
        return int(n or 0)

    async def add_report(self, report: MediaReport) -> None:
        """Insert."""
        await self.save_report(report)

    async def get_report(self, report_id: UUID) -> MediaReport | None:
        """One report."""
        row = await self._s.get(t.MediaReportRow, report_id)
        return _report(row) if row else None

    async def save_report(self, report: MediaReport) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.MediaReportRow, report))

    async def reports_for(self, media_id: UUID) -> builtins.list[MediaReport]:
        """All reports of an item, oldest first."""
        rows = await self._s.scalars(
            select(t.MediaReportRow)
            .where(t.MediaReportRow.media_id == media_id)
            .order_by(t.MediaReportRow.created_at)
        )
        return [_report(r) for r in rows]

    async def list_for_review(
        self, state: str, club_id: UUID | None, limit: int, offset: int
    ) -> tuple[builtins.list[Media], int]:
        """Reported or hidden items with the total."""
        if state == "hidden":
            cond = t.MediaRow.status == MediaStatus.HIDDEN.value
        else:
            cond = and_(
                t.MediaRow.status.in_(
                    [MediaStatus.READY.value, MediaStatus.HIDDEN.value]
                ),
                exists().where(
                    t.MediaReportRow.media_id == t.MediaRow.id,
                    t.MediaReportRow.status == ReportStatus.OPEN.value,
                ),
            )
        if club_id is not None:
            cond = and_(cond, t.MediaRow.club_id == club_id)
        total = await self._s.scalar(
            select(func.count()).select_from(t.MediaRow).where(cond)
        )
        rows = await self._s.scalars(
            select(t.MediaRow)
            .where(cond)
            .order_by(t.MediaRow.updated_at.desc(), t.MediaRow.id)
            .limit(limit)
            .offset(offset)
        )
        return [_media(r) for r in rows], int(total or 0)

    async def list_deleted_before(self, cutoff: datetime) -> builtins.list[Media]:
        """Soft-deleted items older than the cutoff whose files still exist."""
        rows = await self._s.scalars(
            select(t.MediaRow).where(
                t.MediaRow.status == MediaStatus.DELETED.value,
                t.MediaRow.deleted_at < cutoff,
                t.MediaRow.original_file_id.is_not(None),
            )
        )
        return [_media(r) for r in rows]

    async def list_stale(
        self, usage_staged: bool, status: MediaStatus, cutoff: datetime
    ) -> builtins.list[Media]:
        """Staged items (any live status) or items in ``status`` made before cutoff."""
        if usage_staged:
            cond = and_(
                t.MediaRow.usage == MediaUsage.STAGED.value,
                t.MediaRow.status != MediaStatus.DELETED.value,
            )
        else:
            cond = t.MediaRow.status == status.value
        rows = await self._s.scalars(
            select(t.MediaRow).where(cond, t.MediaRow.created_at < cutoff)
        )
        return [_media(r) for r in rows]

    async def add_block(self, block: MediaBlock) -> None:
        """Bar a user; repeating for the same scope is a no-op."""
        cond = (
            t.MediaBlockRow.club_id.is_(None)
            if block.club_id is None
            else t.MediaBlockRow.club_id == block.club_id
        )
        found = await self._s.scalar(
            select(t.MediaBlockRow.id).where(
                t.MediaBlockRow.user_id == block.user_id, cond
            )
        )
        if found is None:
            await self._upsert(_dump(t.MediaBlockRow, block))

    async def remove_block(self, user_id: UUID, club_id: UUID | None) -> None:
        """Lift a block."""
        cond = (
            t.MediaBlockRow.club_id.is_(None)
            if club_id is None
            else t.MediaBlockRow.club_id == club_id
        )
        rows = await self._s.scalars(
            select(t.MediaBlockRow).where(t.MediaBlockRow.user_id == user_id, cond)
        )
        for row in rows:
            await self._s.delete(row)
        await self._s.flush()

    async def is_blocked(self, user_id: UUID, club_id: UUID) -> bool:
        """Barred in this club or everywhere."""
        found = await self._s.scalar(
            select(t.MediaBlockRow.id).where(
                t.MediaBlockRow.user_id == user_id,
                or_(
                    t.MediaBlockRow.club_id.is_(None),
                    t.MediaBlockRow.club_id == club_id,
                ),
            )
        )
        return found is not None

    async def list_blocks(self, club_id: UUID | None) -> builtins.list[MediaBlock]:
        """Blocks of a club (None = global)."""
        cond = (
            t.MediaBlockRow.club_id.is_(None)
            if club_id is None
            else t.MediaBlockRow.club_id == club_id
        )
        rows = await self._s.scalars(
            select(t.MediaBlockRow).where(cond).order_by(t.MediaBlockRow.created_at)
        )
        return [_load(MediaBlock, r) for r in rows]

    async def overrides(self, club_id: UUID) -> ClubMediaOverrides:
        """The club's limit overrides."""
        row = (
            await self._s.execute(
                select(
                    t.ClubRow.media_photo_max_bytes,
                    t.ClubRow.media_video_max_bytes,
                    t.ClubRow.media_quota_bytes,
                ).where(t.ClubRow.id == club_id)
            )
        ).one_or_none()
        return ClubMediaOverrides(*row) if row else ClubMediaOverrides()

    async def set_overrides(self, club_id: UUID, value: ClubMediaOverrides) -> None:
        """Replace the overrides."""
        await self._s.execute(
            update(t.ClubRow)
            .where(t.ClubRow.id == club_id)
            .values(
                media_photo_max_bytes=value.photo_max_bytes,
                media_video_max_bytes=value.video_max_bytes,
                media_quota_bytes=value.quota_bytes,
            )
        )
