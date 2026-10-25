"""The on/off switch of UniLibrary: the environment, then Administration's override."""

from app.modules.library.domain.errors import ExternalDisabledError
from app.modules.library.ports.external_settings import (
    ExternalFlags,
    ExternalSettingsStore,
)
from app.settings import LibrarySettings


class ExternalGate:
    """Says whether UniLibrary is on; every user-facing external call asks it first.

    Other areas ask `flags()` for `anonymous_cards`; nothing outside this area calls
    UniLibrary.
    """

    def __init__(self, settings: LibrarySettings, store: ExternalSettingsStore) -> None:
        """Take the environment defaults and the store of the override."""
        self.settings = settings
        self.store = store

    async def flags(self) -> ExternalFlags:
        """The effective switches: the override if present, else the environment."""
        override = await self.store.override()
        enabled = (
            override.enabled
            if override.enabled is not None
            else self.settings.unilibrary_enabled
        )
        anonymous = (
            override.anonymous_cards
            if override.anonymous_cards is not None
            else self.settings.unilibrary_anonymous_cards
        )
        return ExternalFlags(enabled=enabled, anonymous_cards=anonymous)

    async def ensure_enabled(self) -> ExternalFlags:
        """The flags, or `ExternalDisabledError` (404) while UniLibrary is off."""
        flags = await self.flags()
        if not flags.enabled:
            raise ExternalDisabledError
        return flags
