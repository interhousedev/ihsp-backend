"""taskiq broker, scheduler and the TaskKicker implementation."""

import asyncio
from typing import Any

from app.interfaces.jobs.schedule import CronScheduleSource
from app.settings import load_settings
from app.shared.tasks import TaskKickFailedError

import structlog
from redis.exceptions import RedisError
from taskiq import InMemoryBroker, SmartRetryMiddleware, TaskiqScheduler
from taskiq.abc.broker import AsyncBroker
from taskiq.exceptions import TaskiqError, UnknownTaskError
from taskiq.kicker import AsyncKicker
from taskiq.schedule_sources import LabelScheduleSource
from taskiq.serializers import JSONSerializer
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

log = structlog.get_logger(__name__)

# A message not acknowledged for this long is handed to another worker. The longest
# task (`academic.sync_all`, about 21 minutes) must finish well inside it.
IDLE_TIMEOUT_MS = 90 * 60 * 1000

# Tasks declared `retry_on_error=True` are retried with exponential backoff and
# jitter: 5 s, then 10 s, 20 s ... up to five minutes between attempts.
RETRY_COUNT = 3
RETRY_FIRST_DELAY_SECONDS = 5.0
RETRY_MAX_DELAY_SECONDS = 300.0

# One enqueue is tried twice before the caller is told; the pause between them.
KICK_RETRY_DELAY_SECONDS = 0.2
KICK_FAILURES = (RedisError, OSError, TaskiqError)


def build_broker(redis_url: str, *, in_memory: bool = False) -> AsyncBroker:
    """Create the Redis stream broker, or an in-memory one for tests."""
    if in_memory:
        return InMemoryBroker()
    backend: Any = RedisAsyncResultBackend(
        redis_url=redis_url,
        result_ex_time=3600,
        serializer=JSONSerializer(),
    )
    stream: Any = RedisStreamBroker(
        url=redis_url,
        queue_name="ihsp:jobs",
        consumer_group_name="ihsp-workers",
        maxlen=100_000,
        approximate=True,
        idle_timeout=IDLE_TIMEOUT_MS,
        xread_block=2000,
    )
    broker: AsyncBroker = stream.with_result_backend(backend).with_middlewares(
        retry_middleware()
    )
    return broker


def retry_middleware() -> SmartRetryMiddleware:
    """Backoff-with-jitter retries for the tasks that opted in (`retry_on_error`)."""
    return SmartRetryMiddleware(
        default_retry_count=RETRY_COUNT,
        default_retry_label=False,
        default_delay=RETRY_FIRST_DELAY_SECONDS,
        use_jitter=True,
        use_delay_exponent=True,
        max_delay_exponent=RETRY_MAX_DELAY_SECONDS,
    )


class TaskiqKicker:
    """TaskKicker over taskiq: start a task by its name after commit."""

    def __init__(
        self, broker: AsyncBroker, *, retry_delay: float = KICK_RETRY_DELAY_SECONDS
    ) -> None:
        """Store the broker (the process must have called broker.startup())."""
        self._broker = broker
        self._retry_delay = retry_delay

    async def kick(self, task_name: str, **kwargs: Any) -> None:
        """Enqueue the task, trying twice.

        Raises:
            TaskKickFailedError: The broker refused both attempts; the caller must
                not pretend the work is scheduled (its row would stay `processing`).
        """
        try:
            await self._send(task_name, kwargs)
            return
        except KICK_FAILURES as exc:
            if _is_unknown_task(exc):
                # Only the in-memory broker (tests) knows which tasks exist; the
                # stream broker sends any name and the worker resolves it.
                log.warning("task_kick_unknown_task", task_name=task_name)
                return
            log.warning("task_kick_retry", task_name=task_name, exc_info=True)
        await asyncio.sleep(self._retry_delay)
        try:
            await self._send(task_name, kwargs)
        except KICK_FAILURES as exc:
            log.exception("task_kick_failed", task_name=task_name)
            raise TaskKickFailedError(
                params={"task": task_name},
                support_details=f"{task_name}: {type(exc).__name__}",
            ) from exc

    async def _send(self, task_name: str, kwargs: dict[str, Any]) -> None:
        task = self._broker.find_task(task_name)
        if task is not None:
            await task.kiq(**kwargs)
        else:
            # Task module not imported in this process (e.g. the API).
            await AsyncKicker(task_name, self._broker, {}).kiq(**kwargs)


def _is_unknown_task(exc: BaseException) -> bool:
    """Say whether taskiq raised (or wrapped) UnknownTaskError."""
    return isinstance(exc, UnknownTaskError) or isinstance(
        exc.__cause__, UnknownTaskError
    )


_settings = load_settings()
broker: AsyncBroker = build_broker(
    _settings.redis.url, in_memory=_settings.env == "test"
)
scheduler = TaskiqScheduler(
    broker=broker,
    sources=[CronScheduleSource(settings=_settings), LabelScheduleSource(broker)],
)
