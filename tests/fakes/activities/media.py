"""In-memory fakes of the club media ports."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.modules.activities.domain.media import (
    ClubMediaOverrides,
    MediaKind,
    MediaStatus,
    MediaUsage,
    MediaVariant,
)
from app.modules.activities.ports.gateways import (
    Derivative,
    MediaProbe,
    StoredFile,
    UploadTicket,
)

from uuid_utils.compat import uuid7


class AlbumsFake:
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    async def add(self, album: Any) -> None:
        self.rows[album.id] = deepcopy(album)

    save = add

    async def get(self, album_id: UUID) -> Any:
        return deepcopy(self.rows.get(album_id))

    async def get_by_source_ref(self, ref: str) -> Any:
        return next(
            (deepcopy(a) for a in self.rows.values() if a.source_ref == ref), None
        )

    async def root_for_event(self, event_id: UUID) -> Any:
        return next(
            (
                deepcopy(a)
                for a in self.rows.values()
                if a.event_id == event_id and a.deleted_at is None
            ),
            None,
        )

    async def list_children(self, club_id: UUID, parent_id: UUID | None) -> list[Any]:
        return [
            deepcopy(a)
            for a in self.rows.values()
            if a.club_id == club_id
            and a.parent_id == parent_id
            and a.deleted_at is None
        ]

    async def item_counts(self, ids: list[UUID]) -> dict[UUID, tuple[int, int]]:
        return {i: (0, 0) for i in ids}


class MediaFake:
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}
        self.reports: dict[UUID, Any] = {}
        self.blocks: list[Any] = []
        self.limits: dict[UUID, ClubMediaOverrides] = {}

    async def add(self, media: Any) -> None:
        self.rows[media.id] = deepcopy(media)

    save = add

    async def remove(self, media_id: UUID) -> None:
        self.rows.pop(media_id, None)

    async def get(self, media_id: UUID) -> Any:
        return deepcopy(self.rows.get(media_id))

    async def get_many(self, ids: list[UUID]) -> list[Any]:
        return [deepcopy(self.rows[i]) for i in ids if i in self.rows]

    async def get_by_source_ref(self, ref: str) -> Any:
        return next(
            (deepcopy(m) for m in self.rows.values() if m.source_ref == ref), None
        )

    async def find_duplicate(self, album_id: UUID, sha: str) -> Any:
        return next(
            (
                deepcopy(m)
                for m in self.rows.values()
                if m.album_id == album_id
                and m.content_sha256 == sha
                and m.status != MediaStatus.DELETED
            ),
            None,
        )

    async def list_album(
        self, album_id: UUID, *, statuses: Any, kind: Any, after: Any, limit: int
    ) -> list[Any]:
        items = sorted(
            (
                m
                for m in self.rows.values()
                if m.album_id == album_id
                and m.status in statuses
                and (kind is None or m.kind == kind)
            ),
            key=lambda m: (m.position, m.id),
        )
        if after is not None:
            items = [m for m in items if (m.position, m.id) > after]
        return [deepcopy(m) for m in items[:limit]]

    async def list_for_announcement(self, announcement_id: UUID) -> list[Any]:
        return [
            deepcopy(m)
            for m in self.rows.values()
            if m.announcement_id == announcement_id and m.status != MediaStatus.DELETED
        ]

    async def count_album(self, album_id: UUID) -> int:
        return sum(
            1
            for m in self.rows.values()
            if m.album_id == album_id
            and m.status not in (MediaStatus.DELETED, MediaStatus.FAILED)
        )

    async def next_position(self, album_id: UUID) -> int:
        pos = [m.position for m in self.rows.values() if m.album_id == album_id]
        return max(pos) + 1 if pos else 0

    async def used_bytes(self, club_id: UUID) -> int:
        return sum(
            m.byte_size
            for m in self.rows.values()
            if m.club_id == club_id and m.status != MediaStatus.DELETED
        )

    async def used_bytes_locked(self, club_id: UUID) -> int:
        return await self.used_bytes(club_id)

    async def item_count(self, club_id: UUID) -> int:
        return sum(
            1
            for m in self.rows.values()
            if m.club_id == club_id and m.status != MediaStatus.DELETED
        )

    async def add_report(self, report: Any) -> None:
        self.reports[report.id] = deepcopy(report)

    save_report = add_report

    async def get_report(self, report_id: UUID) -> Any:
        return deepcopy(self.reports.get(report_id))

    async def reports_for(self, media_id: UUID) -> list[Any]:
        return [deepcopy(r) for r in self.reports.values() if r.media_id == media_id]

    async def list_for_review(
        self, state: str, club_id: UUID | None, limit: int, offset: int
    ) -> tuple[list[Any], int]:
        items = [
            m
            for m in self.rows.values()
            if (club_id is None or m.club_id == club_id)
            and (
                m.status == MediaStatus.HIDDEN
                if state == "hidden"
                else any(
                    r.media_id == m.id and r.status.value == "open"
                    for r in self.reports.values()
                )
            )
        ]
        return [deepcopy(m) for m in items[offset : offset + limit]], len(items)

    async def list_deleted_before(self, cutoff: datetime) -> list[Any]:
        return [
            deepcopy(m)
            for m in self.rows.values()
            if m.status == MediaStatus.DELETED
            and m.deleted_at < cutoff
            and m.original_file_id
        ]

    async def list_stale(
        self, usage_staged: bool, status: MediaStatus, cutoff: datetime
    ) -> list[Any]:
        out = []
        for m in self.rows.values():
            if m.created_at >= cutoff:
                continue
            if (
                usage_staged
                and m.usage == MediaUsage.STAGED
                and m.status != MediaStatus.DELETED
            ):
                out.append(deepcopy(m))
            elif not usage_staged and m.status == status:
                out.append(deepcopy(m))
        return out

    async def add_block(self, block: Any) -> None:
        if not any(
            b.user_id == block.user_id and b.club_id == block.club_id
            for b in self.blocks
        ):
            self.blocks.append(deepcopy(block))

    async def remove_block(self, user_id: UUID, club_id: UUID | None) -> None:
        self.blocks = [
            b
            for b in self.blocks
            if not (b.user_id == user_id and b.club_id == club_id)
        ]

    async def is_blocked(self, user_id: UUID, club_id: UUID) -> bool:
        return any(
            b.user_id == user_id and b.club_id in (None, club_id) for b in self.blocks
        )

    async def list_blocks(self, club_id: UUID | None) -> list[Any]:
        return [deepcopy(b) for b in self.blocks if b.club_id == club_id]

    async def overrides(self, club_id: UUID) -> ClubMediaOverrides:
        return self.limits.get(club_id, ClubMediaOverrides())

    async def set_overrides(self, club_id: UUID, value: ClubMediaOverrides) -> None:
        self.limits[club_id] = value


class MediaStoreFake:
    def __init__(self) -> None:
        self.files: dict[UUID, StoredFile] = {}
        self.deleted: list[UUID] = []
        self.adopted: list[UUID] = []

    async def request_upload(
        self,
        *,
        club_id: UUID,
        name: str,
        size: int,
        content_type: str,
        sha256_b64: str,
        max_bytes: int,
    ) -> UploadTicket:
        fid = uuid7()
        self.files[fid] = StoredFile(
            fid, club_id, name, content_type, size, "pending", None
        )
        return UploadTicket(fid, f"http://s3/{fid}", "PUT", {})

    async def complete(self, file_id: UUID) -> StoredFile:
        return self.files[file_id]

    async def info(self, file_id: UUID) -> StoredFile | None:
        return self.files.get(file_id)

    async def download_to(self, file_id: UUID, path: str) -> None:
        Path(path).write_bytes(b"o" * self.files[file_id].byte_size)

    async def store_path(
        self, *, club_id: UUID, name: str, path: str, content_type: str
    ) -> UUID:
        fid = uuid7()
        self.files[fid] = StoredFile(
            fid, club_id, name, content_type, Path(path).stat().st_size, "ready", None
        )
        return fid

    async def read_bytes(self, file_id: UUID) -> bytes:
        return b""

    async def download_url(self, file_id: UUID, *, ttl_seconds: int) -> str:
        return f"http://s3/{file_id}"

    async def delete(self, file_id: UUID) -> None:
        self.deleted.append(file_id)

    async def adopt(self, file_ids: list[UUID], club_id: UUID) -> None:
        self.adopted.extend(file_ids)


class MediaProcessorFake:
    def __init__(self) -> None:
        self.reject = False

    async def probe(self, path: Path) -> MediaProbe:
        if self.reject:
            from app.modules.activities.domain.media import MediaTypeNotAllowedError

            raise MediaTypeNotAllowedError()
        return MediaProbe(MediaKind.PHOTO, "image/webp", 40, 30, None)

    async def make_derivatives(
        self, path: Path, probe: MediaProbe, out_dir: Path
    ) -> list[Derivative]:
        out_dir.mkdir(parents=True, exist_ok=True)
        made = []
        for variant in (MediaVariant.THUMB, MediaVariant.PREVIEW):
            f = out_dir / f"{variant.value}.webp"
            f.write_bytes(b"x" * 10)
            made.append(Derivative(variant, f, "image/webp", 40, 30))
        return made


class MediaKickerFake:
    def __init__(self) -> None:
        self.kicked: list[UUID] = []

    async def process(self, media_id: UUID) -> None:
        self.kicked.append(media_id)
