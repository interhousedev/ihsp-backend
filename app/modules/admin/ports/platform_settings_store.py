"""Storage port of the platform settings."""

from typing import Any, Protocol
from uuid import UUID


class PlatformSettingsStore(Protocol):
    """Reads and writes the key-value rows of ``admin.platform_settings``."""

    async def read_all(self) -> dict[str, Any]:
        """Return every stored key with its value."""
        ...

    async def write(self, values: dict[str, Any], *, updated_by: UUID) -> None:
        """Insert or update the given keys in one transaction."""
        ...
