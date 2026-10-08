"""taskiq broker, scheduler and the TaskKicker implementation."""

from typing import Any

from app.interfaces.jobs.schedule import CronScheduleSource
from app.settings import load_settings

import structlog
from redis.exceptions import RedisError
from taskiq import InMemoryBroker, SimpleRetryMiddleware, TaskiqScheduler
from taskiq.abc.broker import AsyncBroker
from taskiq.exceptions import TaskiqError
from taskiq.kicker import AsyncKicker
from taskiq.schedule_sources import LabelScheduleSource
from taskiq.serializers import JSONSerializer
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

log = structlog.get_logger(__name__)

# A message not acknowledged for this long is handed to another worker. The longest
# task (`academic.sync_all`, about 21 minutes) must finish well inside it.
IDLE_TIMEOUT_MS = 90 * 60 * 1000


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
        SimpleRetryMiddleware(default_retry_count=3)
    )
    return broker


class TaskiqKicker:
    """TaskKicker over taskiq: start a task by its name after commit."""

    def __init__(self, broker: AsyncBroker) -> None:
        """Store the broker (the process must have called broker.startup())."""
        self._broker = broker

    async def kick(self, task_name: str, **kwargs: Any) -> None:
        """Enqueue the task; a broker outage is logged and swallowed."""
        try:
            task = self._broker.find_task(task_name)
            if task is not None:
                await task.kiq(**kwargs)
            else:
                # Task module not imported in this process (e.g. the API).
                await AsyncKicker(task_name, self._broker, {}).kiq(**kwargs)
        except (RedisError, OSError, TaskiqError):
            log.exception("task_kick_failed", task_name=task_name)


_settings = load_settings()
broker: AsyncBroker = build_broker(
    _settings.redis.url, in_memory=_settings.env == "test"
)
scheduler = TaskiqScheduler(
    broker=broker, sources=[CronScheduleSource(), LabelScheduleSource(broker)]
)
