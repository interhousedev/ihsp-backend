"""Redis implementation of `SyncControl` (every process sees the same flags)."""

from uuid import UUID

from app.modules.academic.application.marks.ports.sync_control import SyncControl
from app.shared.emis_pause import EmisPause
from app.shared.redis_util import text, wait

from redis.asyncio import Redis

RUN_STOP_KEY = "academic:sync:stop:run:{}"
STUDENT_STOP_KEY = "academic:sync:stop:student:{}"
RESUME_KEY = "academic:sync:resume"
STOP_TTL_SECONDS = 2 * 60 * 60  # a stale flag expires with a crashed run's lock
RESUME_TTL_SECONDS = 6 * 60 * 60


class RedisSyncControl(SyncControl):
    """Stop flags, the resume marker, and the shared EMIS pause."""

    def __init__(self, redis: Redis, pause: EmisPause) -> None:
        """Keep the Redis client and the EMIS pause."""
        self.redis = redis
        self._pause = pause

    async def request_run_stop(self, run_id: UUID) -> None:
        """Set the stop flag of the run."""
        await wait(
            self.redis.set(RUN_STOP_KEY.format(run_id), "1", ex=STOP_TTL_SECONDS)
        )

    async def run_stop_requested(self, run_id: UUID) -> bool:
        """Whether the run has a stop flag."""
        return bool(await wait(self.redis.exists(RUN_STOP_KEY.format(run_id))))

    async def clear_run_stop(self, run_id: UUID) -> None:
        """Delete the stop flag of the run."""
        await wait(self.redis.delete(RUN_STOP_KEY.format(run_id)))

    async def request_student_stop(self, user_id: UUID) -> None:
        """Set the stop flag of the student sync."""
        await wait(
            self.redis.set(STUDENT_STOP_KEY.format(user_id), "1", ex=STOP_TTL_SECONDS)
        )

    async def student_stop_requested(self, user_id: UUID) -> bool:
        """Whether the student sync has a stop flag."""
        return bool(await wait(self.redis.exists(STUDENT_STOP_KEY.format(user_id))))

    async def clear_student_stop(self, user_id: UUID) -> None:
        """Delete the stop flag of the student sync."""
        await wait(self.redis.delete(STUDENT_STOP_KEY.format(user_id)))

    async def emis_pause_seconds(self) -> float:
        """Seconds of the shared EMIS pause still to come."""
        return await self._pause.remaining()

    async def set_resume(self, slot: str) -> None:
        """Store the slot of the paused run."""
        await wait(self.redis.set(RESUME_KEY, slot, ex=RESUME_TTL_SECONDS))

    async def take_resume(self) -> str | None:
        """Read and delete the resume marker."""
        value = await wait(self.redis.getdel(RESUME_KEY))
        return None if value is None else text(value)
