"""Redis store of guest answers (`guest-answer:{token}`, JSON)."""

import json
from datetime import datetime

from app.modules.links.ports.guest_answers import StoredGuestAnswer

from redis.asyncio import Redis


def _key(token: str) -> str:
    return f"guest-answer:{token}"


class RedisGuestAnswerStore:
    """Stores the text and creation time of a shared guest answer."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def put(
        self, token: str, answer: StoredGuestAnswer, ttl_seconds: int
    ) -> None:
        """Save the answer with a time to live."""
        payload = json.dumps(
            {"text": answer.text, "created_at": answer.created_at.isoformat()}
        )
        await self.redis.set(_key(token), payload, ex=ttl_seconds)

    async def get(self, token: str) -> StoredGuestAnswer | None:
        """Return the answer or None when unknown or expired."""
        value = await self.redis.get(_key(token))
        if value is None:
            return None
        data = json.loads(value)
        return StoredGuestAnswer(
            text=str(data["text"]),
            created_at=datetime.fromisoformat(str(data["created_at"])),
        )
