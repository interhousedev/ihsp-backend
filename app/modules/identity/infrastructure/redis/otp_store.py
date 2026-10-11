"""One-time codes in Redis (spec → Redis keys: otp:{purpose}:{key})."""

import hmac

from app.shared.base_error import RateLimitedError
from app.shared.ids import hash_token, random_digits
from app.shared.redis_util import wait

from redis.asyncio import Redis

OTP_TTL_SECONDS = 300
OTP_COOLDOWN_SECONDS = 60
OTP_ATTEMPTS = 3
CODE_LENGTH = 6


def _text(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value


class RedisOtpStore:
    """Six digit codes: 5 minutes, 3 attempts, a new one only after 60 seconds."""

    def __init__(self, redis: Redis) -> None:
        """Keep the client."""
        self._redis = redis

    @staticmethod
    def _key(purpose: str, subject_key: str) -> str:
        return f"otp:{purpose}:{subject_key}"

    @staticmethod
    def _digest(key: str, code: str) -> str:
        # Salted with the key so a leaked Redis dump cannot be rainbow-tabled.
        return hash_token(f"{key}:{code}")

    async def issue(
        self,
        purpose: str,
        subject_key: str,
        *,
        ttl: int = OTP_TTL_SECONDS,
        cooldown: int | None = OTP_COOLDOWN_SECONDS,
    ) -> str:
        """Create a code; a cooldown stops floods of codes to one subject."""
        key = self._key(purpose, subject_key)
        if cooldown:
            cooldown_key = f"otp:cooldown:{purpose}:{subject_key}"
            if not await self._redis.set(cooldown_key, "1", nx=True, ex=cooldown):
                remaining = int(await self._redis.ttl(cooldown_key))
                raise RateLimitedError(params={"retry_after": max(remaining, 1)})
        code = random_digits(CODE_LENGTH)
        pipe = self._redis.pipeline(transaction=True)
        pipe.delete(key)
        pipe.hset(key, mapping={"h": self._digest(key, code), "a": OTP_ATTEMPTS})
        pipe.expire(key, ttl)
        await pipe.execute()
        return code

    async def verify(self, purpose: str, subject_key: str, code: str) -> bool:
        """Check a code; the attempt is spent before comparing."""
        key = self._key(purpose, subject_key)
        stored = _text(await wait(self._redis.hget(key, "h")))
        if stored is None:
            return False
        attempts = int(await wait(self._redis.hincrby(key, "a", -1)))
        if attempts < 0:
            await self._redis.delete(key)
            return False
        if hmac.compare_digest(stored, self._digest(key, code)):
            await self._redis.delete(key)
            return True
        if attempts == 0:
            await self._redis.delete(key)
        return False

    async def attempts_left(self, purpose: str, subject_key: str) -> int:
        """Attempts remaining for the current code."""
        value = _text(
            await wait(self._redis.hget(self._key(purpose, subject_key), "a"))
        )
        return max(int(value), 0) if value is not None else 0

    async def discard(self, purpose: str, subject_key: str) -> None:
        """Drop the code."""
        await self._redis.delete(self._key(purpose, subject_key))
