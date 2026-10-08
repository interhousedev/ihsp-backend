"""Starting background tasks after commit."""

from typing import Any, Protocol


class TaskKicker(Protocol):
    """Starts a named taskiq task with keyword arguments."""

    async def kick(self, task_name: str, **kwargs: Any) -> None:
        """Enqueue the task; never raises for a broker outage (logs instead)."""
        ...
