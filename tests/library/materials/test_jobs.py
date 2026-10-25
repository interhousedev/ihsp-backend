"""LIB-13, LIB-14: the daily tasks run the maintenance use cases."""

import datetime as dt
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from uuid import UUID

from app.interfaces.jobs.context import set_container
from app.interfaces.jobs.tasks.library.purge import purge
from app.interfaces.jobs.tasks.library.remind_queue import remind_queue
from app.interfaces.jobs.tasks.library.rights_review import rights_review
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.notifications import NotificationDraft
from tests.fakes.clock import FixedClock

MakePending = Callable[..., Awaitable[UUID]]


async def test_the_tasks_have_their_wire_names() -> None:
    """The cron entries LIB-B registers use these names."""
    assert remind_queue.task_name == "library.remind_queue"
    assert rights_review.task_name == "library.rights_review"
    assert purge.task_name == "library.purge"


async def test_remind_queue_runs_through_the_container(
    library: LibraryServices,
    student: Actor,
    make_pending: MakePending,
    clock: FixedClock,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-13: the task returns the number of reminders it queued."""
    await make_pending(student)
    clock.set(clock.now() + dt.timedelta(days=3))
    set_container(SimpleNamespace(library=library))  # type: ignore[arg-type]

    sent = await remind_queue()

    assert sent == 3
    assert await rights_review() == 0
    assert await purge() == 0
