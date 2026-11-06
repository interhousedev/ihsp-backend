"""Stands in for a tool backend whose work package has not been wired yet."""

from collections.abc import Awaitable, Callable
from typing import Any


class NotWired:
    """Any awaited method raises NotImplementedError; the guard hides it as internal."""

    def __init__(self, name: str) -> None:
        """Remember what is missing, for the log."""
        self._name = name

    def __getattr__(self, method: str) -> Callable[..., Awaitable[Any]]:
        """Return a coroutine function that always refuses."""

        async def refuse(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            raise NotImplementedError(f"{self._name}.{method} is not wired")

        return refuse
