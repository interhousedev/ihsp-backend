"""The last calls to UniLibrary, for the admin status page."""

import json
from datetime import datetime

from app.shared.redis_util import wait
from app.modules.library.ports.external_monitor import CallRecord
from app.shared.clock import Clock

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

KEY = "library:ext:calls"
KEEP = 50


class CallLog:
    """A capped Redis list, newest first."""

    def __init__(self, redis: Redis, clock: Clock) -> None:
        """Store the client and the clock."""
        self.redis = redis
        self.clock = clock

    async def record(self, *, ok: bool, ms: int, path: str) -> None:
        """Note one call (the path has no query string)."""
        entry = json.dumps(
            {"at": self.clock.now().isoformat(), "ok": ok, "ms": ms, "path": path}
        )
        try:
            await wait(self.redis.lpush(KEY, entry))
            await wait(self.redis.ltrim(KEY, 0, KEEP - 1))
        except RedisError:
            log.warning("library_unilibrary_call_log_unavailable")

    async def recent(self, limit: int) -> list[CallRecord]:
        """The latest calls, newest first."""
        try:
            raw = await wait(self.redis.lrange(KEY, 0, max(limit, 1) - 1))
        except RedisError:
            return []
        records = []
        for line in raw:
            data = json.loads(line)
            records.append(
                CallRecord(
                    at=datetime.fromisoformat(data["at"]),
                    ok=bool(data["ok"]),
                    ms=int(data["ms"]),
                    path=str(data["path"]),
                )
            )
        return records
