"""Ports: storage of profiles, devices and their activity."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.faces.domain.models import Device, DeviceCall, FaceProfile, Passage


class ProfileRepository(Protocol):
    """Face profiles."""

    async def get(self, user_id: UUID) -> FaceProfile | None:
        """Return the profile or None."""
        ...

    async def save(self, profile: FaceProfile) -> None:
        """Insert or replace the user's profile."""
        ...

    async def delete(self, user_id: UUID) -> None:
        """Remove the profile."""
        ...

    async def embeddings(self) -> list[tuple[UUID, list[float]]]:
        """Return every stored embedding."""
        ...


class DeviceRepository(Protocol):
    """Entrance devices."""

    async def add(self, device: Device) -> None:
        """Insert a device."""
        ...

    async def get(self, device_id: UUID) -> Device | None:
        """Return the device or None."""
        ...

    async def by_hash(self, key_hash: str) -> Device | None:
        """Return the device with this token hash or None."""
        ...

    async def list_all(self) -> list[Device]:
        """Return all devices, newest first."""
        ...

    async def revoke(self, device_id: UUID, at: datetime) -> None:
        """Mark the device revoked (a revoked device stays revoked)."""
        ...

    async def touch(self, device_id: UUID, at: datetime) -> None:
        """Record the last use."""
        ...


class ActivityRepository(Protocol):
    """Device calls and passages (kept for a week)."""

    async def add_call(self, call: DeviceCall) -> None:
        """Insert a call."""
        ...

    async def add_passage(self, passage: Passage) -> None:
        """Insert a passage."""
        ...

    async def calls(self, device_id: UUID, since: datetime) -> list[DeviceCall]:
        """Return the device's calls since the moment, newest first."""
        ...

    async def purge_before(self, cutoff: datetime) -> int:
        """Delete calls and passages older than the cutoff; return how many."""
        ...
