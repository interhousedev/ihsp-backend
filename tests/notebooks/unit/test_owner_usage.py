"""Background notebook jobs run as their owner: the guard and the ledger see them.

A revoked owner's model call is refused inside the job's block; a live owner's call
reaches the provider and is recorded under the owner, not as a system call.
"""

from datetime import date
from typing import Any
from uuid import UUID

from app.modules.ai.infrastructure.access_guard import AccessGuardedLlmGateway
from app.modules.notebooks.application.owner_usage import owner_usage
from app.settings import LimitsSettings
from app.shared.ai_access import AiAccess
from app.shared.contracts.ai import AiAccessRevokedError, LlmTuning
from app.shared.ids import new_id
from app.shared.limits import EffectiveLimits, LimitSnapshot
from app.shared.usage_context import current_usage_actor

import pytest


class RecordingInner:
    """Counts the calls that reach the provider and who they were made for."""

    def __init__(self) -> None:
        self.users: list[UUID | None] = []

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.users.append(current_usage_actor().user_id)
        return {"text": "ok", "tool_calls": [], "usage": {}}

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    def stream(self, **kwargs: Any) -> Any:
        raise NotImplementedError


def _limits(revoked: dict[UUID, AiAccess]) -> EffectiveLimits:
    async def load() -> LimitSnapshot:
        return LimitSnapshot(ai_access=revoked)

    return EffectiveLimits(LimitsSettings(), load, today=lambda: date(2026, 10, 25))


async def _complete(gate: AccessGuardedLlmGateway) -> None:
    await gate.complete(
        model="m",
        system="s",
        messages=[],
        tools=[],
        max_tokens=10,
        tuning=LlmTuning(task="source_guide"),
    )


async def test_a_revoked_owner_job_call_is_refused_before_the_provider() -> None:
    owner = new_id()
    inner = RecordingInner()
    limits = _limits({owner: AiAccess(notebooks_blocked=True)})
    gate = AccessGuardedLlmGateway(inner, limits)

    with pytest.raises(AiAccessRevokedError):
        async with owner_usage(limits, owner):
            await _complete(gate)

    assert inner.users == []


async def test_a_live_owner_job_call_is_recorded_as_the_owner() -> None:
    owner = new_id()
    inner = RecordingInner()
    limits = _limits({})
    gate = AccessGuardedLlmGateway(inner, limits)

    async with owner_usage(limits, owner):
        assert current_usage_actor().user_id == owner
        await _complete(gate)

    assert inner.users == [owner]
    assert current_usage_actor().user_id is None


async def test_the_binding_is_undone_when_the_job_fails() -> None:
    owner = new_id()
    limits = _limits({})

    with pytest.raises(RuntimeError):
        async with owner_usage(limits, owner):
            raise RuntimeError("boom")

    assert current_usage_actor().user_id is None
