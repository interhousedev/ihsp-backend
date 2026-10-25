"""Port: the runtime switches of UniLibrary that Administration sets."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FlagsOverride:
    """What Administration set; a flag that was never set is None."""

    enabled: bool | None = None
    anonymous_cards: bool | None = None


@dataclass(frozen=True, slots=True)
class ExternalFlags:
    """The effective switches: the override if present, else the environment."""

    enabled: bool
    anonymous_cards: bool


class ExternalSettingsStore(Protocol):
    """Keeps the override outside the environment so no restart is needed."""

    async def override(self) -> FlagsOverride:
        """What Administration stored; empty when nothing was set."""
        ...

    async def save(self, flags: ExternalFlags) -> None:
        """Store both switches as the override."""
        ...
