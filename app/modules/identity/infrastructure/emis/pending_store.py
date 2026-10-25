"""Redis storage of 30-minute flows: ``reg:{hash}`` and ``reclaim:{hash}``."""

from datetime import timedelta
from typing import Generic, TypeVar

from app.shared.ids import hash_token, random_token

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

PENDING_TTL = timedelta(minutes=30)
T = TypeVar("T", bound=BaseModel)


class RedisPendingStore(Generic[T]):
    """Bearer-token keyed JSON values; the token itself is never stored."""

    def __init__(
        self,
        redis: Redis,
        *,
        prefix: str,
        model: type[T],
        ttl: timedelta = PENDING_TTL,
    ) -> None:
        """Remember the key prefix, the value model and the lifetime."""
        self._redis = redis
        self._prefix = prefix
        self._model = model
        self._ttl = ttl

    def _key(self, token: str) -> str:
        return f"{self._prefix}:{hash_token(token)}"

    async def create(self, value: T) -> str:
        """Store the value under a new random token and return the token."""
        token = random_token()
        await self._redis.set(
            self._key(token), value.model_dump_json(), ex=int(self._ttl.total_seconds())
        )
        return token

    async def get(self, token: str) -> T | None:
        """Load the value, or None when it expired or the token is unknown."""
        raw = await self._redis.get(self._key(token))
        if raw is None:
            return None
        try:
            return self._model.model_validate_json(raw)
        except ValidationError:
            return None

    async def save(self, token: str, value: T) -> None:
        """Overwrite the value without extending its lifetime."""
        await self._redis.set(self._key(token), value.model_dump_json(), keepttl=True)

    async def delete(self, token: str) -> None:
        """Forget the value."""
        await self._redis.delete(self._key(token))
