"""A Redis claim that lets one worker write the guide of a shared document."""

from uuid import UUID

from app.shared.ids import random_token

from redis.asyncio import Redis

CLAIM_TTL_SECONDS = 120  # longer than a guide call with its retries


class RedisGuideLock:
    """Implements GuideLock with `SET NX EX` on `nb:guide:{document}:{language}`."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def try_claim(self, document_id: UUID, language: str) -> str | None:
        """Claim the guide; None when another worker is writing it."""
        token = random_token(12)
        key = f"nb:guide:{document_id}:{language}"
        taken = await self.redis.set(key, token, nx=True, ex=CLAIM_TTL_SECONDS)
        return token if taken else None

    async def release(self, document_id: UUID, language: str, token: str) -> None:
        """Delete the claim if it is still ours."""
        key = f"nb:guide:{document_id}:{language}"
        current = await self.redis.get(key)
        if current is not None and _text(current) == token:
            await self.redis.delete(key)


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
