"""The runtime switches of UniLibrary, kept in Redis (`library:ext:settings`).

`PUT /v1/admin/library/unilibrary/settings` writes them, so Administration can turn
the integration on without a restart. A flag that was never set is None and the
environment value wins; a Redis outage also falls back to the environment.
"""

from app.modules.library.infrastructure.redis_util import wait
from app.modules.library.ports.external_settings import ExternalFlags, FlagsOverride

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

KEY = "library:ext:settings"


def _flag(value: str | None) -> bool | None:
    if value is None:
        return None
    return value == "1"


class RedisExternalSettings:
    """Stores the override as a hash of `"1"` and `"0"`."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def override(self) -> FlagsOverride:
        """What Administration stored; empty when nothing was set or Redis is down."""
        try:
            data = await wait(self.redis.hgetall(KEY))
        except RedisError:
            log.warning("library_unilibrary_settings_unavailable")
            return FlagsOverride()
        return FlagsOverride(
            enabled=_flag(data.get("enabled")),
            anonymous_cards=_flag(data.get("anonymous_cards")),
        )

    async def save(self, flags: ExternalFlags) -> None:
        """Store both switches as the override."""
        await wait(
            self.redis.hset(
                KEY,
                mapping={
                    "enabled": "1" if flags.enabled else "0",
                    "anonymous_cards": "1" if flags.anonymous_cards else "0",
                },
            )
        )
