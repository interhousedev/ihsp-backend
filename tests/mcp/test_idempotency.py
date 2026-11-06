"""An AI retry with the same key creates nothing new."""

from typing import Any
from uuid import uuid4

from app.interfaces.mcp.constants import SCOPES_BY_SERVER
from app.interfaces.mcp.errors import (
    McpIdempotencyConflictError,
    McpIdempotencyInProgressError,
)
from app.interfaces.mcp.idempotency import once
from app.shared.rate_limit import RateLimiter
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of

import pytest
from fakeredis.aioredis import FakeRedis


class _Deps:
    def __init__(self, redis: FakeRedis) -> None:
        self.rate_limiter = RateLimiter(redis)


class _Kit:
    def __init__(self, redis: FakeRedis) -> None:
        self.deps = _Deps(redis)


class _Maker:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> dict[str, Any]:
        self.calls += 1
        return {"id": self.calls}


async def _run(
    kit: Any, user: Any, key: str | None, maker: Any, title: str = "T"
) -> dict[str, Any]:
    return await once(
        kit,
        user_id=user,
        tool="create_test",
        key=key,
        arguments={"title": title},
        create=maker,
    )


async def test_a_retry_returns_the_first_result(redis: FakeRedis) -> None:
    """The second call replays; nothing is created twice."""
    kit, user, maker = _Kit(redis), uuid4(), _Maker()

    first = await _run(kit, user, "key-12345", maker)
    second = await _run(kit, user, "key-12345", maker)

    assert first == second == {"id": 1}
    assert maker.calls == 1


async def test_no_key_always_creates(redis: FakeRedis) -> None:
    """Without a key the tool behaves as before."""
    kit, user, maker = _Kit(redis), uuid4(), _Maker()

    await _run(kit, user, None, maker)
    await _run(kit, user, None, maker)

    assert maker.calls == 2


async def test_the_key_belongs_to_one_user(redis: FakeRedis) -> None:
    """Another person's equal key never returns the first person's result."""
    kit, maker = _Kit(redis), _Maker()

    await _run(kit, uuid4(), "key-12345", maker)
    await _run(kit, uuid4(), "key-12345", maker)

    assert maker.calls == 2


async def test_other_arguments_are_refused(redis: FakeRedis) -> None:
    """A reused key with a different request is a client mistake."""
    kit, user, maker = _Kit(redis), uuid4(), _Maker()

    await _run(kit, user, "key-12345", maker)
    with pytest.raises(McpIdempotencyConflictError):
        await _run(kit, user, "key-12345", maker, title="Other")


async def test_a_failure_frees_the_key(redis: FakeRedis) -> None:
    """A failed creation can be retried with the same key."""
    kit, user, maker = _Kit(redis), uuid4(), _Maker()

    async def fails() -> dict[str, Any]:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _run(kit, user, "key-12345", fails)

    assert await _run(kit, user, "key-12345", maker) == {"id": 1}


async def test_a_call_in_flight_is_refused(redis: FakeRedis) -> None:
    """A parallel retry cannot create a second copy."""
    kit, user = _Kit(redis), uuid4()

    async def nested() -> dict[str, Any]:
        with pytest.raises(McpIdempotencyInProgressError):
            await _run(kit, user, "key-12345", _Maker())
        return {"id": 1}

    assert await _run(kit, user, "key-12345", nested) == {"id": 1}


async def test_a_retry_through_the_server_makes_one_notebook(world: World) -> None:
    """End to end: the tool replays its first result for the same key."""
    token, _ = world.connector_token("student", *SCOPES_BY_SERVER["student"])
    key = "retry-key-1"

    async with world.session("student", token) as session:
        first = await call(session, "create_notebook", title="N", idempotency_key=key)
        again = await call(session, "create_notebook", title="N", idempotency_key=key)

    assert data_of(first)["id"] == data_of(again)["id"]
