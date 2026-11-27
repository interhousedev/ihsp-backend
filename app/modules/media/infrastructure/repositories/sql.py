"""SQL store of media jobs and the weekly usage count."""

from dataclasses import asdict
from datetime import timedelta
from uuid import UUID

from app.modules.media.domain.media_job import MediaJob, MediaKind, MediaStatus
from app.modules.media.domain.narration import NarrationOptions, Segment
from app.modules.media.infrastructure.orm import MediaJobRow
from app.modules.media.ports.media import StaleMediaJobError
from app.shared.clock import Clock

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _segment(data: dict) -> Segment:  # type: ignore[type-arg]
    return Segment(
        id=data["id"],
        speaker=data["speaker"],
        text=data["text"],
        start_ms=data.get("start_ms", 0),
        end_ms=data.get("end_ms", 0),
        source_refs=tuple(data.get("source_refs", ())),
    )


def _to_job(row: MediaJobRow) -> MediaJob:
    return MediaJob(
        id=row.id,
        owner_id=row.owner_id,
        kind=MediaKind(row.kind),
        script=tuple(_segment(s) for s in row.script),
        options=NarrationOptions(**row.options),
        subject_id=row.subject_id,
        group_id=row.group_id,
        created_at=row.created_at,
        status=MediaStatus(row.status),
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        audio_file_id=row.audio_file_id,
        captions_file_id=row.captions_file_id,
        file_id=row.file_id,
        storage_key=row.storage_key,
        segments=tuple(_segment(s) for s in row.segments),
        duration_ms=row.duration_ms,
        error=row.error,
        delivered=row.delivered,
        version=row.version,
    )


def _values(job: MediaJob) -> dict:  # type: ignore[type-arg]
    return {
        "kind": job.kind.value,
        "script": [asdict(s) for s in job.script],
        "options": asdict(job.options),
        "script_hash": job.script_hash,
        "status": job.status.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "audio_file_id": job.audio_file_id,
        "captions_file_id": job.captions_file_id,
        "file_id": job.file_id,
        "storage_key": job.storage_key,
        "segments": [asdict(s) for s in job.segments],
        "duration_ms": job.duration_ms,
        "error": job.error,
        "delivered": job.delivered,
    }


class SqlMediaJobStore:
    """`MediaJobStore`: one short transaction per call."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind the session factory."""
        self.sessionmaker = sessionmaker

    async def add(self, job: MediaJob) -> None:
        """Insert a new job."""
        async with self.sessionmaker.begin() as session:
            session.add(
                MediaJobRow(
                    id=job.id,
                    owner_id=job.owner_id,
                    subject_id=job.subject_id,
                    group_id=job.group_id,
                    created_at=job.created_at,
                    version=job.version,
                    **_values(job),
                )
            )

    async def get(self, job_id: UUID) -> MediaJob | None:
        """The job or None."""
        async with self.sessionmaker() as session:
            row = await session.get(MediaJobRow, job_id)
            return _to_job(row) if row else None

    async def save(self, job: MediaJob) -> None:
        """Compare-and-set on `version`."""
        async with self.sessionmaker.begin() as session:
            result = await session.execute(
                update(MediaJobRow)
                .where(MediaJobRow.id == job.id, MediaJobRow.version == job.version)
                .values(**_values(job), version=job.version + 1, updated_at=func.now())
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                raise StaleMediaJobError(str(job.id))
        job.version += 1

    async def list_by_owner(
        self, owner_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[MediaJob], int]:
        """The owner's jobs, newest first, and the total count."""
        async with self.sessionmaker() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(MediaJobRow)
                .where(MediaJobRow.owner_id == owner_id)
            )
            rows = await session.scalars(
                select(MediaJobRow)
                .where(MediaJobRow.owner_id == owner_id)
                .order_by(MediaJobRow.created_at.desc(), MediaJobRow.id)
                .limit(limit)
                .offset(offset)
            )
            return [_to_job(r) for r in rows], int(total or 0)

    async def find_done(self, owner_id: UUID, script_hash: str) -> list[MediaJob]:
        """DONE jobs of the owner with this hash."""
        async with self.sessionmaker() as session:
            rows = await session.scalars(
                select(MediaJobRow)
                .where(
                    MediaJobRow.owner_id == owner_id,
                    MediaJobRow.script_hash == script_hash,
                    MediaJobRow.status == MediaStatus.DONE.value,
                )
                .order_by(MediaJobRow.created_at)
            )
            return [_to_job(r) for r in rows]

    async def list_undelivered(self, limit: int = 50) -> list[UUID]:
        """Ids of DONE jobs the notebook has not accepted yet."""
        async with self.sessionmaker() as session:
            rows = await session.scalars(
                select(MediaJobRow.id)
                .where(
                    MediaJobRow.status == MediaStatus.DONE.value,
                    MediaJobRow.delivered.is_(False),
                )
                .limit(limit)
            )
            return list(rows)


class SqlMediaLimits:
    """Weekly allowance counted from the jobs table."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        media_jobs_per_week: int,
    ) -> None:
        """Bind the session factory, clock and the allowance."""
        self.sessionmaker = sessionmaker
        self.clock = clock
        self.media_jobs_per_week = media_jobs_per_week

    async def used_this_week(self, owner_id: UUID) -> int:
        """Jobs created in the last 7 days."""
        since = self.clock.now() - timedelta(days=7)
        async with self.sessionmaker() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(MediaJobRow)
                .where(
                    MediaJobRow.owner_id == owner_id, MediaJobRow.created_at >= since
                )
            )
            return int(count or 0)
