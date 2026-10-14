"""Where a student's full EMIS sync state lives: Redis, or memory for tests and dev."""

import datetime as dt
import json
from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.schedule.student_sync_state import (
    SyncState,
    SyncStatus,
)

from redis.asyncio import Redis

STATE_TTL_SECONDS = 30 * 24 * 3600


def _dump(state: SyncState) -> str:
    return json.dumps(
        {
            "status": state.status,
            "requested_at": state.requested_at.isoformat(),
            "finished_at": state.finished_at.isoformat() if state.finished_at else None,
            "detail": state.detail,
        }
    )


def _load(raw: str) -> SyncState:
    data = json.loads(raw)
    finished = data.get("finished_at")
    status: SyncStatus = data["status"]
    return SyncState(
        status=status,
        requested_at=dt.datetime.fromisoformat(data["requested_at"]),
        finished_at=dt.datetime.fromisoformat(finished) if finished else None,
        detail=data.get("detail"),
    )


class RedisSyncState:
    """``me-sync:{user}`` holds the state, ``rl:me-sync:{user}`` the window."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def get(self, user_id: UUID) -> SyncState | None:
        """Return the last sync, or None if there was none."""
        raw = await self.redis.get(f"me-sync:{user_id}")
        return _load(raw) if raw else None

    async def put(self, user_id: UUID, state: SyncState) -> None:
        """Replace the last sync (kept for thirty days)."""
        await self.redis.set(f"me-sync:{user_id}", _dump(state), ex=STATE_TTL_SECONDS)

    async def claim(self, user_id: UUID, *, seconds: int) -> int | None:
        """SET NX EX: atomic, so two quick clicks never start two syncs."""
        key = f"rl:me-sync:{user_id}"
        if await self.redis.set(key, "1", nx=True, ex=seconds):
            return None
        return max(int(await self.redis.ttl(key)), 1)


class MemorySyncState:
    """The same store in memory (unit tests, fake wiring)."""

    def __init__(self, now: Callable[[], dt.datetime]) -> None:
        """Start empty; ``now`` decides when a window ends."""
        self._now = now
        self._states: dict[UUID, SyncState] = {}
        self._windows: dict[UUID, dt.datetime] = {}

    async def get(self, user_id: UUID) -> SyncState | None:
        """Return the last sync, or None if there was none."""
        return self._states.get(user_id)

    async def put(self, user_id: UUID, state: SyncState) -> None:
        """Replace the last sync."""
        self._states[user_id] = state

    async def claim(self, user_id: UUID, *, seconds: int) -> int | None:
        """Take the window unless it is still open."""
        now = self._now()
        ends = self._windows.get(user_id)
        if ends is not None and ends > now:
            return max(int((ends - now).total_seconds()), 1)
        self._windows[user_id] = now + dt.timedelta(seconds=seconds)
        return None
