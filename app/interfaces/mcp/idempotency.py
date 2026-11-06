"""Idempotency keys of MCP create tools: an AI retry returns the first result."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Final
from uuid import UUID

from app.interfaces.mcp.errors import (
    McpIdempotencyConflictError,
    McpIdempotencyInProgressError,
)
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

RESULT_TTL_SECONDS: Final = 24 * 60 * 60
CLAIM_TTL_SECONDS: Final = 5 * 60
_PENDING: Final = "pending"

IdempotencyKey = Annotated[
    str | None,
    Field(
        min_length=8,
        max_length=128,
        description=(
            "Optional random id for this creation. Retrying with the same id within "
            "24 hours returns the first result and creates nothing new."
        ),
    ),
]


def _fingerprint(arguments: dict[str, Any]) -> str:
    text = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


async def once(
    kit: ToolKit,
    *,
    user_id: UUID,
    tool: str,
    key: str | None,
    arguments: dict[str, Any],
    create: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run `create` once per user, tool and key; without a key, always run it.

    A failed creation frees the key, so it can be retried. Reusing a key with other
    arguments, or while the first call still runs, is refused.
    """
    if key is None:
        return await create()
    redis = kit.deps.rate_limiter.redis
    hashed = hashlib.sha256(key.encode()).hexdigest()
    slot = f"mcp:idempotency:{user_id}:{tool}:{hashed}"
    fingerprint = _fingerprint(arguments)
    claim = json.dumps({"state": _PENDING, "fingerprint": fingerprint})
    if not await redis.set(slot, claim, nx=True, ex=CLAIM_TTL_SECONDS):
        stored = await redis.get(slot)
        if stored is None:
            raise McpIdempotencyInProgressError()
        entry = json.loads(stored)
        if entry["fingerprint"] != fingerprint:
            raise McpIdempotencyConflictError()
        if entry["state"] == _PENDING:
            raise McpIdempotencyInProgressError()
        replayed: dict[str, Any] = entry["result"]
        return replayed
    try:
        result = await create()
    except BaseException:
        await redis.delete(slot)
        raise
    done = {"state": "done", "fingerprint": fingerprint, "result": result}
    await redis.set(slot, json.dumps(done, default=str), ex=RESULT_TTL_SECONDS)
    return result
