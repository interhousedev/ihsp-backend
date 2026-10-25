"""AI-ACCESS: the central gate refuses revoked users before any model call.

The gate sits under the usage ledger, so web chat, notebooks, Studio, the bot and MCP
tools all reach it. Staff are refused only when a flag is set for them.
"""

from datetime import date
from typing import Any
from uuid import UUID

from app.modules.ai.infrastructure.access_guard import AccessGuardedLlmGateway
from app.modules.notebooks.application.budget import NotebookBudget
from app.settings import LimitsSettings
from app.shared.ai_access import AiAccess
from app.shared.contracts.ai import AiAccessRevokedError, LlmTuning
from app.shared.ids import new_id
from app.shared.limits import EffectiveLimits, LimitSnapshot
from app.shared.usage_context import (
    bind_ai_scope,
    bind_usage_user,
    reset_ai_scope,
    reset_usage_actor,
)

import pytest


class RecordingInner:
    """Counts the calls that reach the provider."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("complete")
        return {"text": "ok", "tool_calls": [], "usage": {}}

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("complete_json")
        return {"data": {}, "text": "{}", "usage": {}}

    async def stream(self, **kwargs: Any) -> Any:
        self.calls.append("stream")
        yield {"delta": "hi"}


def _limits(revoked: dict[UUID, AiAccess]) -> EffectiveLimits:
    async def load() -> LimitSnapshot:
        return LimitSnapshot(ai_access=revoked)

    return EffectiveLimits(LimitsSettings(), load, today=lambda: date(2026, 10, 25))


def _tuning(task: str) -> LlmTuning:
    return LlmTuning(task=task)


async def _complete(gate: AccessGuardedLlmGateway, task: str) -> None:
    await gate.complete(
        model="m",
        system="s",
        messages=[],
        tools=[],
        max_tokens=10,
        tuning=_tuning(task),
    )


async def test_a_chat_revoked_user_is_refused_on_chat_and_never_reaches_the_model() -> (
    None
):
    user = new_id()
    inner = RecordingInner()
    gate = AccessGuardedLlmGateway(inner, _limits({user: AiAccess(chat_blocked=True)}))
    token = bind_usage_user(user, unlimited=False)

    try:
        with pytest.raises(AiAccessRevokedError) as raised:
            await _complete(gate, "student_chat")
    finally:
        reset_usage_actor(token)

    assert raised.value.params == {"scope": "chat"}
    assert inner.calls == []


async def test_a_chat_revoked_user_still_reaches_notebooks() -> None:
    user = new_id()
    inner = RecordingInner()
    gate = AccessGuardedLlmGateway(inner, _limits({user: AiAccess(chat_blocked=True)}))
    token = bind_usage_user(user, unlimited=False)

    try:
        await _complete(gate, "notebook_chat")
    finally:
        reset_usage_actor(token)

    assert inner.calls == ["complete"]


async def test_a_notebooks_revoked_user_is_refused_on_studio_and_notebook_chat() -> (
    None
):
    user = new_id()
    inner = RecordingInner()
    gate = AccessGuardedLlmGateway(
        inner, _limits({user: AiAccess(notebooks_blocked=True)})
    )
    token = bind_usage_user(user, unlimited=False)

    try:
        for task in ("notebook_chat", "studio_flashcards", "studio_quiz"):
            with pytest.raises(AiAccessRevokedError) as raised:
                await _complete(gate, task)
            assert raised.value.params == {"scope": "notebooks"}
        await _complete(gate, "student_chat")
    finally:
        reset_usage_actor(token)

    assert inner.calls == ["complete"]


async def test_staff_are_refused_only_when_their_flag_is_set() -> None:
    teacher = new_id()
    blocked_teacher = new_id()
    inner = RecordingInner()
    gate = AccessGuardedLlmGateway(
        inner, _limits({blocked_teacher: AiAccess(chat_blocked=True)})
    )

    token = bind_usage_user(teacher, unlimited=True)
    try:
        await _complete(gate, "admin_chat")
    finally:
        reset_usage_actor(token)
    token = bind_usage_user(blocked_teacher, unlimited=True)
    try:
        with pytest.raises(AiAccessRevokedError):
            await _complete(gate, "admin_chat")
    finally:
        reset_usage_actor(token)

    assert inner.calls == ["complete"]


async def test_a_system_call_without_a_user_is_not_restricted() -> None:
    inner = RecordingInner()
    gate = AccessGuardedLlmGateway(inner, _limits({new_id(): AiAccess(True, True)}))

    await _complete(gate, "notebook_chat")

    assert inner.calls == ["complete"]


async def test_discovery_follows_the_scope_its_caller_bound() -> None:
    """Discovery is shared by chat and notebooks; the caller's bound scope decides."""
    user = new_id()
    inner = RecordingInner()
    gate = AccessGuardedLlmGateway(
        inner, _limits({user: AiAccess(notebooks_blocked=True)})
    )
    token = bind_usage_user(user, unlimited=False)
    scope_token = bind_ai_scope("notebooks")
    try:
        with pytest.raises(AiAccessRevokedError) as raised:
            await _complete(gate, "discover")
    finally:
        reset_ai_scope(scope_token)
        reset_usage_actor(token)
    assert raised.value.params == {"scope": "notebooks"}
    assert inner.calls == []


async def test_discovery_outside_notebooks_is_judged_as_chat() -> None:
    user = new_id()
    inner = RecordingInner()
    gate = AccessGuardedLlmGateway(
        inner, _limits({user: AiAccess(notebooks_blocked=True)})
    )
    token = bind_usage_user(user, unlimited=False)
    try:
        await _complete(gate, "discover")
    finally:
        reset_usage_actor(token)
    assert inner.calls == ["complete"]


async def test_notebook_budget_refuses_a_revoked_user_before_anything_runs() -> None:
    user = new_id()
    pool = NotebookBudget(
        store=None,  # type: ignore[arg-type]  # the access check reads no counters
        clock=None,  # type: ignore[arg-type]
        settings=None,  # type: ignore[arg-type]  # not read by the access check
        limits=_limits({user: AiAccess(notebooks_blocked=True)}),
    )
    with pytest.raises(AiAccessRevokedError):
        await pool.require_access(user)
    await NotebookBudget(
        store=None,  # type: ignore[arg-type]
        clock=None,  # type: ignore[arg-type]
        settings=None,  # type: ignore[arg-type]
        limits=_limits({user: AiAccess(chat_blocked=True)}),
    ).require_access(user)


async def test_json_and_stream_calls_are_refused_too() -> None:
    user = new_id()
    inner = RecordingInner()
    gate = AccessGuardedLlmGateway(
        inner, _limits({user: AiAccess(notebooks_blocked=True)})
    )
    token = bind_usage_user(user, unlimited=False)

    try:
        with pytest.raises(AiAccessRevokedError):
            await gate.complete_json(
                model="m",
                system="s",
                messages=[],
                schema_name="x",
                schema={},
                max_tokens=10,
                tuning=_tuning("source_guide"),
            )
        stream = gate.stream(
            model="m",
            system="s",
            messages=[],
            max_tokens=10,
            tuning=_tuning("studio_report"),
        )
        with pytest.raises(AiAccessRevokedError):
            await anext(stream)
    finally:
        reset_usage_actor(token)

    assert inner.calls == []
