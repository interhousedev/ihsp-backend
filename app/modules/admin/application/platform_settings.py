"""Read and change the runtime platform settings (admin only)."""

from typing import Any

from app.modules.admin.domain.platform_settings import (
    PlatformSettings,
    apply_changes,
    from_stored,
)
from app.modules.admin.ports.platform_settings_store import PlatformSettingsStore
from app.shared.actor import Actor, Role


class PlatformSettingsService:
    """School info and safe defaults kept in the database."""

    def __init__(self, store: PlatformSettingsStore) -> None:
        """Keep the store."""
        self.store = store

    async def get(self, actor: Actor) -> PlatformSettings:
        """Return the settings; keys never saved have their defaults."""
        actor.require(Role.ADMIN)
        return await self.current()

    async def current(self) -> PlatformSettings:
        """Return the settings without an actor check (for other modules)."""
        return from_stored(await self.store.read_all())

    async def update(self, actor: Actor, changes: dict[str, Any]) -> PlatformSettings:
        """Validate and save the given keys; the rest keep their values."""
        actor.require(Role.ADMIN)
        updated = apply_changes(await self.current(), changes)
        await self.store.write(
            {key: getattr(updated, key) for key in changes}, updated_by=actor.user_id
        )
        return updated
