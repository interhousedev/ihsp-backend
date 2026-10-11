"""Redis counters of daily outputs per kind and the set of running outputs."""

from datetime import date, timedelta
from uuid import UUID

from app.shared.redis_util import wait

from redis.asyncio import Redis

DAY_TTL = timedelta(hours=48)
RUNNING_TTL = timedelta(hours=1)  # self-heals if a finished output was never removed


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


STUDENT_PREFIX = "nb"  # outputs of students' notebooks
COURSE_PREFIX = "lms"  # outputs of course workspaces (counted per staff member)


class RedisQuotaStore:
    """Implements QuotaStore with `{prefix}:quota:*` counters and `:running:*` sets."""

    def __init__(self, redis: Redis, prefix: str = STUDENT_PREFIX) -> None:
        """Store the Redis client and the key prefix of the pool."""
        self.redis = redis
        self.prefix = prefix

    def _quota_key(self, user_id: UUID, day: date, kind: str) -> str:
        return f"{self.prefix}:quota:{user_id}:{day.isoformat()}:{kind}"

    def _running_key(self, user_id: UUID) -> str:
        return f"{self.prefix}:running:{user_id}"

    async def used(self, user_id: UUID, day: date, kind: str) -> int:
        """How many outputs of the kind were counted that day."""
        value = await self.redis.get(self._quota_key(user_id, day, kind))
        return int(_text(value)) if value is not None else 0

    async def add(self, user_id: UUID, day: date, kind: str) -> int:
        """Count one output; return the new value."""
        key = self._quota_key(user_id, day, kind)
        value = int(await wait(self.redis.incr(key)))
        await self.redis.expire(key, int(DAY_TTL.total_seconds()))
        return value

    async def remove(self, user_id: UUID, day: date, kind: str) -> None:
        """Undo one count; the counter never goes below zero."""
        key = self._quota_key(user_id, day, kind)
        if int(await wait(self.redis.decr(key))) < 0:
            await self.redis.set(key, 0, ex=int(DAY_TTL.total_seconds()))

    async def running(self, user_id: UUID) -> set[UUID]:
        """Ids of the user's running outputs."""
        raw = await wait(self.redis.smembers(self._running_key(user_id)))
        return {UUID(_text(item)) for item in raw}

    async def add_running(self, user_id: UUID, artifact_id: UUID) -> None:
        """Mark an output as running."""
        key = self._running_key(user_id)
        await wait(self.redis.sadd(key, str(artifact_id)))
        await self.redis.expire(key, int(RUNNING_TTL.total_seconds()))

    async def remove_running(self, user_id: UUID, artifact_id: UUID) -> None:
        """Mark an output as finished."""
        await wait(self.redis.srem(self._running_key(user_id), str(artifact_id)))

    async def clear(self, user_id: UUID) -> None:
        """Forget the user's running outputs."""
        await self.redis.delete(self._running_key(user_id))
