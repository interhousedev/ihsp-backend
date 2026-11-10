"""Entrance devices: create, list, revoke, read their calls."""

from datetime import timedelta
from uuid import UUID

from app.modules.faces.application.views import CallView, CreatedDevice
from app.modules.faces.domain.device_token import mint_token
from app.modules.faces.domain.errors import DeviceNameError, DeviceNotFoundError
from app.modules.faces.domain.models import (
    RETENTION_DAYS,
    Device,
    normalize_name,
)
from app.modules.faces.ports.directory import StudentDirectory
from app.modules.faces.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateDevice:
    """Register a device and hand out its token once."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, admin_id: UUID, name: str) -> CreatedDevice:
        """Create the device; only the token hash is stored."""
        clean = normalize_name(name)
        if clean is None:
            raise DeviceNameError()
        minted = mint_token()
        device = Device(
            id=new_id(),
            name=clean,
            key_prefix=minted.key_prefix,
            key_hash=minted.key_hash,
            created_by=admin_id,
            created_at=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.devices.add(device)
            await uow.commit()
        return CreatedDevice(
            id=device.id,
            name=device.name,
            key_prefix=device.key_prefix,
            created_at=device.created_at,
            token=minted.token,
        )


class ListDevices:
    """All devices, newest first."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependency."""
        self._uow_factory = uow_factory

    async def execute(self) -> list[Device]:
        """Return every device."""
        async with self._uow_factory() as uow:
            return await uow.devices.list_all()


class RevokeDevice:
    """Stop a device's token from working."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, device_id: UUID) -> Device:
        """Revoke the device; repeating the call changes nothing."""
        async with self._uow_factory() as uow:
            device = await uow.devices.get(device_id)
            if device is None:
                raise DeviceNotFoundError()
            if device.revoked_at is None:
                await uow.devices.revoke(device_id, self._clock.now())
                await uow.commit()
            revoked = await uow.devices.get(device_id)
        if revoked is None:
            raise DeviceNotFoundError()
        return revoked


class ListDeviceCalls:
    """The calls of one device in the retention window."""

    def __init__(
        self, *, uow_factory: UowFactory, directory: StudentDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._directory = directory
        self._clock = clock

    async def execute(self, device_id: UUID) -> list[CallView]:
        """Return the last seven days of calls, newest first."""
        since = self._clock.now() - timedelta(days=RETENTION_DAYS)
        async with self._uow_factory() as uow:
            if await uow.devices.get(device_id) is None:
                raise DeviceNotFoundError()
            calls = await uow.activity.calls(device_id, since)
        ids = list({c.matched_user_id for c in calls if c.matched_user_id})
        names = await self._directory.full_names(ids) if ids else {}
        return [
            CallView(
                id=c.id,
                at=c.at,
                status=c.status.value,
                matched_user_id=c.matched_user_id,
                matched_name=(
                    names.get(c.matched_user_id) if c.matched_user_id else None
                ),
                excused=c.excused,
            )
            for c in calls
        ]


class PurgeOld:
    """Drop calls and passages past the retention window."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self) -> int:
        """Delete rows older than seven days; return how many."""
        cutoff = self._clock.now() - timedelta(days=RETENTION_DAYS)
        async with self._uow_factory() as uow:
            removed = await uow.activity.purge_before(cutoff)
            await uow.commit()
        return removed
