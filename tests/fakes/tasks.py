"""A task kicker that only records what it was asked to start."""

from typing import Any


class FakeTaskKicker:
    """Records (task_name, kwargs) pairs."""

    def __init__(self) -> None:
        """Start with no calls."""
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def kick(self, task_name: str, **kwargs: Any) -> None:
        """Record the call."""
        self.calls.append((task_name, kwargs))

    def names(self) -> list[str]:
        """Return only the task names, in order."""
        return [name for name, _ in self.calls]
