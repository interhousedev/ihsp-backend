"""Starting background tasks after commit."""

from typing import Any, Protocol

from app.shared.base_error import BaseError


class TaskKickFailedError(BaseError):
    """The task broker refused the task; the work is not scheduled."""

    code = "tasks/kick-failed"
    status = 503
    message_key = "error-internal"


class TaskKicker(Protocol):
    """Starts a named taskiq task with keyword arguments."""

    async def kick(self, task_name: str, **kwargs: Any) -> None:
        """Enqueue the task.

        Raises:
            TaskKickFailedError: The broker is down and the task was not enqueued.
        """
        ...
