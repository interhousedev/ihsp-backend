"""Typing helper for redis-py calls (stubs type results as `Awaitable | value`)."""

from collections.abc import Awaitable
from typing import TypeVar, cast

T = TypeVar("T")


async def wait(call: Awaitable[T] | T) -> T:
    """Await a redis-py call."""
    return await cast("Awaitable[T]", call)
