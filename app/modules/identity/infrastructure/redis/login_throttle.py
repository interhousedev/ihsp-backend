"""Back-off for failed passwords and counters for failed passwordless codes."""

from uuid import UUID

from app.modules.identity.domain.errors import AccountLockedError
from app.modules.identity.ports.login_throttle import FailureCounts

from redis.asyncio import Redis

FREE_ATTEMPTS = 5
COUNT_TTL_SECONDS = 3600
LOCK_SECONDS = (60, 300, 900)  # 5th, 6th and later failures
OTP_FAILURE_TTL_SECONDS = 86400


class RedisLoginThrottle:
    """Failures are counted per (login, IP) so a stranger cannot lock the owner out."""

    def __init__(self, redis: Redis) -> None:
        """Keep the client."""
        self._redis = redis

    @staticmethod
    def _pair(login: str, ip: str) -> str:
        return f"{login.strip().lower()}:{ip}"

    async def check(self, login: str, ip: str) -> None:
        """Raise AccountLockedError while the pair is locked."""
        remaining = int(await self._redis.ttl(f"lf-lock:{self._pair(login, ip)}"))
        if remaining > 0:
            raise AccountLockedError(params={"retry_after": remaining})

    async def record_failure(
        self, login: str, ip: str, user_id: UUID | None
    ) -> FailureCounts:
        """Count one failure; lock the pair from the fifth one on."""
        pair = self._pair(login, ip)
        count = int(await self._redis.incr(f"lf:{pair}"))
        await self._redis.expire(f"lf:{pair}", COUNT_TTL_SECONDS)
        if count >= FREE_ATTEMPTS:
            step = min(count - FREE_ATTEMPTS, len(LOCK_SECONDS) - 1)
            await self._redis.set(f"lf-lock:{pair}", "1", ex=LOCK_SECONDS[step])
        account = 0
        if user_id is not None:
            account = int(await self._redis.incr(f"lfu:{user_id}"))
            await self._redis.expire(f"lfu:{user_id}", COUNT_TTL_SECONDS)
        return FailureCounts(for_login_and_ip=count, for_account=account)

    async def reset(self, login: str, ip: str) -> None:
        """Forget the pair's failures."""
        pair = self._pair(login, ip)
        await self._redis.delete(f"lf:{pair}", f"lf-lock:{pair}")

    async def otp_failures(self, user_id: UUID, ip: str) -> int:
        """Wrong passwordless codes today."""
        value = await self._redis.get(f"otp-fail:{user_id}:{ip}")
        if value is None:
            return 0
        return int(value.decode() if isinstance(value, bytes) else value)

    async def record_otp_failure(self, user_id: UUID, ip: str) -> int:
        """Count a wrong passwordless code."""
        key = f"otp-fail:{user_id}:{ip}"
        count = int(await self._redis.incr(key))
        if count == 1:
            await self._redis.expire(key, OTP_FAILURE_TTL_SECONDS)
        return count
