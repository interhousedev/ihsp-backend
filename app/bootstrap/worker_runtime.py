"""Worker child-process hooks: build the container when a taskiq worker starts.

`python -m app worker` lists this module among the modules the taskiq worker imports,
so every worker process registers the hooks before it starts listening.
"""

from app.bootstrap.common import build_container
from app.bootstrap.container import Container
from app.interfaces.jobs.broker import TaskiqKicker, broker
from app.interfaces.jobs.context import set_container
from app.settings import load_settings
from app.shared.logging import configure_logging

from taskiq import TaskiqEvents, TaskiqState


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def start_container(state: TaskiqState) -> None:
    """Build the container of this worker process and publish it to the tasks."""
    settings = load_settings()
    configure_logging(settings.log_level, json_logs=settings.env == "prod")
    container = await build_container(
        settings, process="worker", kicker=TaskiqKicker(broker)
    )
    set_container(container)
    state.container = container


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def stop_container(state: TaskiqState) -> None:
    """Close connections of the worker's container."""
    container: Container | None = getattr(state, "container", None)
    if container is not None:
        await container.close()
