"""Bind a notebook job's owner as the usage user of the model calls it makes.

A background job (taskiq) has no request actor, so its calls would be recorded as
system calls and the AI access guard would let a revoked owner through. The owner
is bound here around the whole run, so the guard refuses a revoked owner and the
ledger counts the call under them.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.shared.limits import LimitsProvider
from app.shared.usage_context import bind_usage_user, reset_usage_actor


@asynccontextmanager
async def owner_usage(
    limits: LimitsProvider | None, user_id: UUID
) -> AsyncIterator[None]:
    """Count and access-check the calls of this block as `user_id`.

    Without a limits provider (tests of modules built without storage) the owner is
    bound as a student; the role only labels the usage ledger.
    """
    unlimited = False
    if limits is not None:
        unlimited = (await limits.for_user(user_id)).unlimited
    token = bind_usage_user(user_id, unlimited=unlimited)
    try:
        yield
    finally:
        reset_usage_actor(token)
