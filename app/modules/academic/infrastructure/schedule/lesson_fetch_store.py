"""The state of one-lesson EMIS fetches in Redis (shared by all processes).

The key of a finished fetch stays: `done` is the negative cache of a lesson EMIS has
nothing for, a failure holds retries back for a moment. A worker that dies leaves a
running key, which expires so that the lesson can be asked again.
"""

import datetime as dt
import json
from uuid import UUID

from app.shared.contracts.mcp_academic import MaterialFetch

from redis.asyncio import Redis

RUNNING_TTL_SECONDS = 300
NEGATIVE_TTL_SECONDS = 6 * 3600
FAILED_TTL_SECONDS = 60
MAX_RUNNING_PER_USER = 3


def _dump(fetch: MaterialFetch) -> str:
    return json.dumps(
        {
            "job_id": fetch.job_id,
            "status": fetch.status,
            "started_at": fetch.started_at.isoformat(),
            "reason": fetch.reason,
        }
    )


def _load(raw: str) -> MaterialFetch:
    data = json.loads(raw)
    return MaterialFetch(
        job_id=data["job_id"],
        status=data["status"],
        started_at=dt.datetime.fromisoformat(data["started_at"]),
        reason=data["reason"],
    )


class RedisLessonFetchStore:
    """One key per lesson, and a sorted set of each user's running fetches."""

    def __init__(self, redis: Redis) -> None:
        """Keep the client (it decodes responses)."""
        self._redis = redis

    async def begin(
        self, lesson_id: UUID, user_id: UUID, fetch: MaterialFetch
    ) -> MaterialFetch | None:
        """Return the lesson's fetch, this one if none ran; None over the user's cap."""
        current = await self.get(lesson_id)
        if current is not None:
            return current
        running = self._user_key(user_id)
        started = fetch.started_at.timestamp()
        await self._redis.zremrangebyscore(
            running, "-inf", started - RUNNING_TTL_SECONDS
        )
        if await self._redis.zcard(running) >= MAX_RUNNING_PER_USER:
            return None
        taken = await self._redis.set(
            self._key(lesson_id), _dump(fetch), nx=True, ex=RUNNING_TTL_SECONDS
        )
        if not taken:
            return await self.get(lesson_id)
        await self._redis.zadd(running, {str(lesson_id): started})
        await self._redis.expire(running, RUNNING_TTL_SECONDS)
        return fetch

    async def get(self, lesson_id: UUID) -> MaterialFetch | None:
        """Return the state, or None when no fetch is remembered."""
        raw = await self._redis.get(self._key(lesson_id))
        return _load(raw) if raw else None

    async def finish(
        self, lesson_id: UUID, user_id: UUID, fetch: MaterialFetch
    ) -> None:
        """Store how the job ended, unless a newer job took the lesson."""
        await self._redis.zrem(self._user_key(user_id), str(lesson_id))
        current = await self.get(lesson_id)
        if current is not None and current.job_id != fetch.job_id:
            return
        ttl = NEGATIVE_TTL_SECONDS if fetch.status == "done" else FAILED_TTL_SECONDS
        await self._redis.set(self._key(lesson_id), _dump(fetch), ex=ttl)

    @staticmethod
    def _key(lesson_id: UUID) -> str:
        return f"mcp:matfetch:{lesson_id}"

    @staticmethod
    def _user_key(user_id: UUID) -> str:
        return f"mcp:matfetch:user:{user_id}"
