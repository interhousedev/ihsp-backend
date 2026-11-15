"""SQL repositories of erasure requests and exports."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.privacy.domain.models import (
    ErasureRequest,
    ErasureStatus,
    ExportJob,
    ExportStatus,
)
from app.modules.privacy.infrastructure.orm import ErasureRequestRow, ExportRow

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_OPEN = (ErasureStatus.PENDING_REVIEW.value, ErasureStatus.APPROVED.value)


def _request(row: ErasureRequestRow) -> ErasureRequest:
    return ErasureRequest(
        id=row.id,
        user_id=row.user_id,
        status=ErasureStatus(row.status),
        requested_at=row.requested_at,
        decided_at=row.decided_at,
        decided_by=row.decided_by,
        reject_reason=row.reject_reason,
        closes_on=row.closes_on,
        completed_at=row.completed_at,
    )


def _export(row: ExportRow) -> ExportJob:
    return ExportJob(
        id=row.id,
        user_id=row.user_id,
        status=ExportStatus(row.status),
        created_at=row.created_at,
        finished_at=row.finished_at,
        expires_at=row.expires_at,
        storage_key=row.storage_key,
        byte_size=row.byte_size,
        error=row.error,
    )


class SqlErasureRepository:
    """Erasure requests."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the session."""
        self.session = session

    async def add(self, request: ErasureRequest) -> None:
        """Insert a request (the partial unique index allows one open per user)."""
        self.session.add(
            ErasureRequestRow(
                id=request.id,
                user_id=request.user_id,
                status=request.status.value,
                requested_at=request.requested_at,
            )
        )
        await self.session.flush()

    async def get(self, request_id: UUID) -> ErasureRequest | None:
        """Return the request or None."""
        row = await self.session.get(ErasureRequestRow, request_id)
        return _request(row) if row else None

    async def get_open(self, user_id: UUID) -> ErasureRequest | None:
        """The user's request in ``pending_review`` or ``approved``."""
        row = await self.session.scalar(
            select(ErasureRequestRow)
            .where(
                ErasureRequestRow.user_id == user_id,
                ErasureRequestRow.status.in_(_OPEN),
            )
            .order_by(ErasureRequestRow.requested_at.desc())
            .limit(1)
        )
        return _request(row) if row else None

    async def list(
        self, status: ErasureStatus | None, *, limit: int, offset: int
    ) -> Sequence[ErasureRequest]:
        """Requests newest first, optionally of one status."""
        stmt = select(ErasureRequestRow).order_by(
            ErasureRequestRow.requested_at.desc(), ErasureRequestRow.id
        )
        if status is not None:
            stmt = stmt.where(ErasureRequestRow.status == status.value)
        rows = await self.session.scalars(stmt.limit(limit).offset(offset))
        return [_request(r) for r in rows]

    async def save(self, request: ErasureRequest) -> None:
        """Write changes."""
        row = await self.session.get(ErasureRequestRow, request.id)
        if row is None:
            raise LookupError(f"erasure request {request.id} does not exist")
        row.status = request.status.value
        row.decided_at = request.decided_at
        row.decided_by = request.decided_by
        row.reject_reason = request.reject_reason
        row.closes_on = request.closes_on
        row.completed_at = request.completed_at
        await self.session.flush()


class SqlExportRepository:
    """Exports."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the session."""
        self.session = session

    async def add(self, job: ExportJob) -> None:
        """Insert an export."""
        self.session.add(
            ExportRow(
                id=job.id,
                user_id=job.user_id,
                status=job.status.value,
                created_at=job.created_at,
            )
        )
        await self.session.flush()

    async def get(self, export_id: UUID) -> ExportJob | None:
        """Return the export or None."""
        row = await self.session.get(ExportRow, export_id)
        return _export(row) if row else None

    async def latest_of(self, user_id: UUID) -> ExportJob | None:
        """The user's newest export that did not fail."""
        row = await self.session.scalar(
            select(ExportRow)
            .where(
                ExportRow.user_id == user_id,
                ExportRow.status != ExportStatus.FAILED.value,
            )
            .order_by(ExportRow.created_at.desc())
            .limit(1)
        )
        return _export(row) if row else None

    async def list_of(self, user_id: UUID, *, limit: int) -> Sequence[ExportJob]:
        """The user's exports, newest first."""
        rows = await self.session.scalars(
            select(ExportRow)
            .where(ExportRow.user_id == user_id)
            .order_by(ExportRow.created_at.desc(), ExportRow.id)
            .limit(limit)
        )
        return [_export(r) for r in rows]

    async def expired(self, now: datetime, *, limit: int) -> Sequence[ExportJob]:
        """Exports with a stored archive whose ``expires_at`` has passed."""
        rows = await self.session.scalars(
            select(ExportRow)
            .where(ExportRow.storage_key.is_not(None), ExportRow.expires_at <= now)
            .order_by(ExportRow.expires_at)
            .limit(limit)
        )
        return [_export(r) for r in rows]

    async def save(self, job: ExportJob) -> None:
        """Write changes."""
        row = await self.session.get(ExportRow, job.id)
        if row is None:
            raise LookupError(f"export {job.id} does not exist")
        row.status = job.status.value
        row.finished_at = job.finished_at
        row.expires_at = job.expires_at
        row.storage_key = job.storage_key
        row.byte_size = job.byte_size
        row.error = job.error
        await self.session.flush()
