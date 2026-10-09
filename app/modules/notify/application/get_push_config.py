"""GET /v1/push/config: what a browser needs to subscribe."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PushConfig:
    """Whether Web Push is on and the public VAPID key to subscribe with."""

    enabled: bool
    vapid_public_key: str | None


class GetPushConfig:
    """Serves the public part of the push settings."""

    def __init__(self, *, enabled: bool, vapid_public_key: str | None) -> None:
        """Store the configuration of this process."""
        self._config = PushConfig(
            enabled=enabled and bool(vapid_public_key),
            vapid_public_key=vapid_public_key if enabled else None,
        )

    def execute(self) -> PushConfig:
        """Return the configuration."""
        return self._config
