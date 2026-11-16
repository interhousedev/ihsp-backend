"""Admin-edited admission settings with a short per-process cache."""

import time
from collections.abc import Callable

from app.modules.admission.domain.runtime_settings import RuntimeSettings
from app.modules.admission.ports.unit_of_work import UowFactory


class RuntimeSettingsService:
    """Reads `admission.runtime_settings` at most once per `ttl` seconds.

    Other processes see an administrator's change within `ttl` (30 s by default).
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        ttl: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Keep the factory, the lifetime in seconds and the clock."""
        self._uow = uow_factory
        self._ttl = ttl
        self._monotonic = monotonic
        self._cached: RuntimeSettings | None = None
        self._read_at = 0.0

    async def get(self) -> RuntimeSettings:
        """Return the snapshot, reloading it when it is older than `ttl`."""
        now = self._monotonic()
        if self._cached is not None and now - self._read_at < self._ttl:
            return self._cached
        async with self._uow() as uow:
            values = await uow.runtime_settings.load()
        self._cached = RuntimeSettings(values)
        self._read_at = now
        return self._cached

    def invalidate(self) -> None:
        """Drop the snapshot (after this process changed a value)."""
        self._cached = None
