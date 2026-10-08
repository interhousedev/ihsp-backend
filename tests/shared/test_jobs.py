"""TaskiqKicker starts tasks by name and never raises for a broker outage."""

from typing import Any

from app.interfaces.jobs.broker import TaskiqKicker, build_broker
from app.interfaces.jobs.context import get_container, set_container

from redis.exceptions import ConnectionError as RedisConnectionError
from taskiq import InMemoryBroker


class BrokenBroker(InMemoryBroker):
    """A broker whose Redis is down."""

    async def kick(self, message: Any) -> None:
        """Fail like a lost connection."""
        raise RedisConnectionError("redis is down")


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


async def test_a_broker_outage_is_logged_and_swallowed() -> None:
    """A dead Redis must not fail a committed use case."""
    broker = BrokenBroker()

    @broker.task(task_name="demo.noop")
    async def noop() -> None:
        return None

    await TaskiqKicker(broker).kick("demo.noop")
    await TaskiqKicker(broker).kick("demo.unknown")


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
