"""Redis counters of the notebook weighted-token budget (§ 4.1, Redis keys)."""

from datetime import date, datetime, timedelta
from uuid import UUID

from app.modules.notebooks.ports.budget_store import SessionWindow
from app.shared.redis_util import wait

from redis.asyncio import Redis

DAY_TTL = timedelta(hours=48)


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


STUDENT_PREFIX = "ai:nb"  # the notebooks pool of students
COURSE_PREFIX = "ai:lms"  # the pool of course staff, shared with the author assistant


class RedisBudgetStore:
    """Implements BudgetStore with `{prefix}:session:*` and `{prefix}:day:*` keys.

    The key layout is the one of the `ai` module, so the same prefix there and here
    (`ai:lms`) means one pool.
    """

    def __init__(self, redis: Redis, prefix: str = STUDENT_PREFIX) -> None:
        """Store the Redis client and the key prefix of the pool."""
        self.redis = redis
        self.prefix = prefix

    def _session_key(self, user_id: UUID) -> str:
        return f"{self.prefix}:session:{user_id}"

    def _day_key(self, user_id: UUID, day: date) -> str:
        return f"{self.prefix}:day:{user_id}:{day.isoformat()}"

    async def session(self, user_id: UUID) -> SessionWindow | None:
        """Return the open session window, if there is one."""
        raw = await wait(self.redis.hgetall(self._session_key(user_id)))
        data = {_text(k): _text(v) for k, v in raw.items()}
        if "ends_at" not in data:
            return None
        return SessionWindow(
            used=int(data.get("used", "0")),
            ends_at=datetime.fromisoformat(data["ends_at"]),
        )

    async def open_session(self, user_id: UUID, ends_at: datetime) -> None:
        """Start a new window with zero tokens used; it expires at `ends_at`."""
        key = self._session_key(user_id)
        await self.redis.delete(key)
        fields = {"used": 0, "ends_at": ends_at.isoformat()}
        await wait(self.redis.hset(key, mapping=fields))
        await self.redis.expireat(key, int(ends_at.timestamp()))

    async def add_session(self, user_id: UUID, tokens: int) -> None:
        """Add tokens to the open window."""
        await wait(self.redis.hincrby(self._session_key(user_id), "used", tokens))

    async def day_used(self, user_id: UUID, day: date) -> int:
        """Return the tokens used on a Tashkent day."""
        value = await self.redis.get(self._day_key(user_id, day))
        return int(_text(value)) if value is not None else 0

    async def add_day(self, user_id: UUID, day: date, tokens: int) -> None:
        """Add tokens to a day's counter (kept for 48 hours)."""
        key = self._day_key(user_id, day)
        await wait(self.redis.incrby(key, tokens))
        await self.redis.expire(key, int(DAY_TTL.total_seconds()))
