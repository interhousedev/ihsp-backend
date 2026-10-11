"""TaskiqKicker starts tasks by name; a broker outage is retried once, then raised."""

from typing import Any

from app.interfaces.jobs.broker import TaskiqKicker, build_broker, retry_middleware
from app.interfaces.jobs.context import get_container, set_container
from app.shared.tasks import TaskKickFailedError

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from taskiq import InMemoryBroker


class BrokenBroker(InMemoryBroker):
    """A broker whose Redis is down for the first `failures` sends."""

    def __init__(self, failures: int = 99) -> None:
        """Fail `failures` times, then work."""
        super().__init__()
        self.failures = failures
        self.attempts = 0

    async def kick(self, message: Any) -> None:
        """Fail like a lost connection while failures remain."""
        self.attempts += 1
        if self.attempts <= self.failures:
            raise RedisConnectionError("redis is down")
        await super().kick(message)


async def test_a_task_is_started_by_its_name() -> None:
    """GEN-8: TaskKicker.kick('<module>.<task>', **kwargs) runs the task."""
    broker = InMemoryBroker()
    seen: list[str] = []

    @broker.task(task_name="demo.greet")
    async def greet(name: str) -> str:
        seen.append(name)
        return f"hi, {name}"

    await broker.startup()
    try:
        await TaskiqKicker(broker).kick("demo.greet", name="Ann")
        await broker.wait_all()
    finally:
        await broker.shutdown()

    assert seen == ["Ann"]


async def test_a_task_unknown_to_this_process_is_still_sent() -> None:
    """The API process need not import task modules; sending must not raise."""
    broker = InMemoryBroker()
    await broker.startup()
    try:
        await TaskiqKicker(broker).kick("elsewhere.task", value=1)
    finally:
        await broker.shutdown()


async def test_a_broker_outage_is_raised_after_a_retry() -> None:
    """The caller learns that nothing is scheduled instead of a silent log line."""
    broker = BrokenBroker()

    @broker.task(task_name="demo.noop")
    async def noop() -> None:
        return None

    kicker = TaskiqKicker(broker, retry_delay=0)
    with pytest.raises(TaskKickFailedError):
        await kicker.kick("demo.noop")
    with pytest.raises(TaskKickFailedError):
        await kicker.kick("demo.unknown")
    assert broker.attempts == 4


async def test_a_single_blip_is_retried_and_the_task_runs() -> None:
    """One failed send is tried again before anyone is told."""
    broker = BrokenBroker(failures=1)
    seen: list[int] = []

    @broker.task(task_name="demo.count")
    async def count(n: int) -> None:
        seen.append(n)

    await broker.startup()
    try:
        await TaskiqKicker(broker, retry_delay=0).kick("demo.count", n=1)
        await broker.wait_all()
    finally:
        await broker.shutdown()

    assert seen == [1]
    assert broker.attempts == 2


def test_task_retries_back_off_with_jitter() -> None:
    """Opt-in retries wait 5 s, then double, capped at five minutes."""
    middleware = retry_middleware()

    assert middleware.default_retry_label is False
    assert middleware.default_retry_count == 3
    assert middleware.default_delay == 5.0
    assert middleware.use_delay_exponent is True
    assert middleware.use_jitter is True
    assert middleware.max_delay_exponent == 300.0


def test_in_memory_broker_is_used_when_asked() -> None:
    """Tests never touch the dev Redis queue."""
    assert isinstance(
        build_broker("redis://localhost:6380/0", in_memory=True), InMemoryBroker
    )


def test_the_worker_container_must_be_set_before_use() -> None:
    """Task functions read the container set by bootstrap/worker.py."""
    sentinel: Any = object()

    set_container(sentinel)

    assert get_container() is sentinel
