"""SQL repositories of the faces module."""

from datetime import datetime
from uuid import UUID

from app.modules.faces.domain.models import (
    CallStatus,
    Device,
    DeviceCall,
    FaceProfile,
    Passage,
)
from app.modules.faces.infrastructure.orm import (
    DeviceCallRow,
    DeviceRow,
    FaceProfileRow,
    PassageRow,
)

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _device(row: DeviceRow) -> Device:
    return Device(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        key_hash=row.key_hash,
        created_by=row.created_by,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
    )


class SqlProfileRepository:
    """Face profiles."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the session."""
        self.session = session

    async def get(self, user_id: UUID) -> FaceProfile | None:
        """Return the profile or None."""
        row = await self.session.get(FaceProfileRow, user_id)
        if row is None:
            return None
        return FaceProfile(
            user_id=row.user_id,
            embedding=list(row.embedding),
            photo_file_id=row.photo_file_id,
            uploaded_by=row.uploaded_by,
            locked=row.locked,
            updated_at=row.updated_at,
        )

    async def save(self, profile: FaceProfile) -> None:
        """Insert or replace the user's profile."""
        values = {
            "user_id": profile.user_id,
            "embedding": profile.embedding,
            "photo_file_id": profile.photo_file_id,
            "uploaded_by": profile.uploaded_by,
            "locked": profile.locked,
            "updated_at": profile.updated_at,
        }
        stmt = insert(FaceProfileRow).values(values)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[FaceProfileRow.user_id],
                set_={k: v for k, v in values.items() if k != "user_id"},
            )
        )

    async def delete(self, user_id: UUID) -> None:
        """Remove the profile."""
        await self.session.execute(
            delete(FaceProfileRow).where(FaceProfileRow.user_id == user_id)
        )

    async def embeddings(self) -> list[tuple[UUID, list[float]]]:
        """Return every stored embedding."""
        rows = await self.session.execute(
            select(FaceProfileRow.user_id, FaceProfileRow.embedding)
        )
        return [(user_id, list(embedding)) for user_id, embedding in rows.all()]


class SqlDeviceRepository:
    """Entrance devices."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the session."""
        self.session = session

    async def add(self, device: Device) -> None:
        """Insert a device."""
        self.session.add(
            DeviceRow(
                id=device.id,
                name=device.name,
                key_prefix=device.key_prefix,
                key_hash=device.key_hash,
                created_by=device.created_by,
                created_at=device.created_at,
            )
        )
        await self.session.flush()

    async def get(self, device_id: UUID) -> Device | None:
        """Return the device or None."""
        row = await self.session.get(DeviceRow, device_id)
        return _device(row) if row else None

    async def by_hash(self, key_hash: str) -> Device | None:
        """Return the device with this token hash or None."""
        row = await self.session.scalar(
            select(DeviceRow).where(DeviceRow.key_hash == key_hash)
        )
        return _device(row) if row else None

    async def list_all(self) -> list[Device]:
        """Return all devices, newest first."""
        rows = await self.session.scalars(
            select(DeviceRow).order_by(DeviceRow.created_at.desc(), DeviceRow.id)
        )
        return [_device(row) for row in rows]

    async def revoke(self, device_id: UUID, at: datetime) -> None:
        """Mark the device revoked (a revoked device stays revoked)."""
        await self.session.execute(
            update(DeviceRow)
            .where(DeviceRow.id == device_id, DeviceRow.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    async def touch(self, device_id: UUID, at: datetime) -> None:
        """Record the last use."""
        await self.session.execute(
            update(DeviceRow).where(DeviceRow.id == device_id).values(last_used_at=at)
        )


class SqlActivityRepository:
    """Device calls and passages."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the session."""
        self.session = session

    async def add_call(self, call: DeviceCall) -> None:
        """Insert a call."""
        self.session.add(
            DeviceCallRow(
                id=call.id,
                device_id=call.device_id,
                at=call.at,
                status=call.status.value,
                matched_user_id=call.matched_user_id,
                excused=call.excused,
            )
        )
        await self.session.flush()

    async def add_passage(self, passage: Passage) -> None:
        """Insert a passage."""
        self.session.add(
            PassageRow(
                id=passage.id,
                device_id=passage.device_id,
                user_id=passage.user_id,
                at=passage.at,
                direction=passage.direction.value,
                excused=passage.excused,
            )
        )
        await self.session.flush()

    async def calls(self, device_id: UUID, since: datetime) -> list[DeviceCall]:
        """Return the device's calls since the moment, newest first."""
        rows = await self.session.scalars(
            select(DeviceCallRow)
            .where(DeviceCallRow.device_id == device_id, DeviceCallRow.at >= since)
            .order_by(DeviceCallRow.at.desc(), DeviceCallRow.id.desc())
            .limit(1000)
        )
        return [
            DeviceCall(
                id=r.id,
                device_id=r.device_id,
                at=r.at,
                status=CallStatus(r.status),
                matched_user_id=r.matched_user_id,
                excused=r.excused,
            )
            for r in rows
        ]

    async def purge_before(self, cutoff: datetime) -> int:
        """Delete calls and passages older than the cutoff; return how many."""
        calls = await self.session.execute(
            delete(DeviceCallRow).where(DeviceCallRow.at < cutoff)
        )
        passages = await self.session.execute(
            delete(PassageRow).where(PassageRow.at < cutoff)
        )
        removed = int(calls.rowcount or 0) + int(passages.rowcount or 0)  # type: ignore[attr-defined]  # noqa: E501
        return removed
