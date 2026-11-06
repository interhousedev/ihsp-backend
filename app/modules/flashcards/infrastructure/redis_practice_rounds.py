"""Redis lists `fc:practice:{user}:{set}:{date}`: the restart round of one day."""

from collections.abc import Sequence
from datetime import date, timedelta
from uuid import UUID

from app.shared.redis_util import wait

from redis.asyncio import Redis

ROUND_TTL = timedelta(hours=48)


class RedisPracticeRounds:
    """Implements PracticeRounds; the date in the key ends a round at midnight."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    @staticmethod
    def _key(owner_id: UUID, set_id: UUID, day: date) -> str:
        return f"fc:practice:{owner_id}:{set_id}:{day.isoformat()}"

    async def start(
        self, owner_id: UUID, set_id: UUID, day: date, card_ids: Sequence[UUID]
    ) -> None:
        """Replace the round with these cards."""
        key = self._key(owner_id, set_id, day)
        await self.redis.delete(key)
        if card_ids:
            await wait(self.redis.rpush(key, *(str(i) for i in card_ids)))
            await self.redis.expire(key, int(ROUND_TTL.total_seconds()))

    async def remaining(self, owner_id: UUID, set_id: UUID, day: date) -> list[UUID]:
        """Return the ids still in the round, next first."""
        key = self._key(owner_id, set_id, day)
        values = await wait(self.redis.lrange(key, 0, -1))
        return [
            UUID(value.decode() if isinstance(value, bytes) else value)
            for value in values
        ]

    async def answered(
        self, owner_id: UUID, set_id: UUID, day: date, card_id: UUID, *, again: bool
    ) -> None:
        """Take the card out of the round; `again` puts it back at the end."""
        key = self._key(owner_id, set_id, day)
        removed = await wait(self.redis.lrem(key, 0, str(card_id)))
        if again and removed:
            await wait(self.redis.rpush(key, str(card_id)))
