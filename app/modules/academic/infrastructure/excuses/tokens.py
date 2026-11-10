"""Redis store of the single-use Telegram decision tokens."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.excuses.ports import DecisionGrant
from app.shared.ids import random_token

from redis.asyncio import Redis

TTL_SECONDS = 7 * 24 * 3600


def _key(token: str) -> str:
    return f"excuse:tok:{token}"


def _index(excuse_id: UUID) -> str:
    return f"excuse:tok-index:{excuse_id}"


class RedisDecisionTokens:
    """Implements DecisionTokens: ``excuse:tok:{token}`` = ``excuse:user:a|r``."""

    def __init__(self, redis: Redis) -> None:
        """Store the client."""
        self.redis = redis

    async def issue(self, excuse_id: UUID, user_id: UUID) -> tuple[str, str]:
        """Return the (approve, reject) tokens, valid for one week."""
        approve, reject = random_token(16), random_token(16)
        pipe = self.redis.pipeline()
        for token, action in ((approve, "a"), (reject, "r")):
            pipe.set(_key(token), f"{excuse_id}:{user_id}:{action}", ex=TTL_SECONDS)
            pipe.sadd(_index(excuse_id), token)
        pipe.expire(_index(excuse_id), TTL_SECONDS)
        await pipe.execute()
        return approve, reject

    async def consume(self, token: str, user_id: UUID) -> DecisionGrant | None:
        """Use the token once; None when unknown, used, expired or not the user's."""
        raw: Any = await self.redis.get(_key(token))
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
        excuse_part, owner_part, action = text.split(":")
        if UUID(owner_part) != user_id:
            return None
        taken: Any = await self.redis.getdel(_key(token))
        if taken is None:
            return None
        return DecisionGrant(UUID(excuse_part), user_id, action == "a")

    async def revoke(self, excuse_id: UUID) -> None:
        """Forget every token of the excuse (it was decided another way)."""
        raw: Any = await self.redis.smembers(_index(excuse_id))  # type: ignore[misc]
        keys = [_key(t.decode() if isinstance(t, bytes) else str(t)) for t in raw]
        if keys:
            await self.redis.delete(*keys)
        await self.redis.delete(_index(excuse_id))
