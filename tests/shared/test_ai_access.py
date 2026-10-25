"""AI-ACCESS: revoked chat and notebook AI, per user, cached for the limits TTL."""

from datetime import date
from uuid import UUID

from app.settings import LimitsSettings
from app.shared.ai_access import AI_TASK_SCOPE, AiAccess, scope_of
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiAccessRevokedError
from app.shared.ids import new_id
from app.shared.limits import EffectiveLimits, LimitSnapshot, StaticLimits

import pytest


def test_every_model_task_belongs_to_exactly_one_scope() -> None:
    assert set(AI_TASK_SCOPE) == set(AiTask)
    assert set(AI_TASK_SCOPE.values()) <= {"chat", "notebooks"}


@pytest.mark.parametrize(
    ("task", "scope"),
    [
        (AiTask.STUDENT_CHAT, "chat"),
        (AiTask.STUDENT_CHAT_SMART, "chat"),
        (AiTask.ADMIN_CHAT, "chat"),
        (AiTask.LMS_AUTHORING, "chat"),
        (AiTask.NOTEBOOK_CHAT, "notebooks"),
        (AiTask.CONTEXT_COMPACT, "notebooks"),
        (AiTask.STUDIO_FLASHCARDS, "notebooks"),
        (AiTask.STUDIO_QUIZ, "notebooks"),
    ],
)
def test_tasks_map_to_chat_or_notebooks(task: AiTask, scope: str) -> None:
    assert AI_TASK_SCOPE[task] == scope


def test_unknown_or_missing_task_counts_as_chat() -> None:
    assert scope_of(None) == "chat"
    assert scope_of("no_such_task") == "chat"
    assert scope_of("notebook_chat") == "notebooks"


def test_access_blocks_only_the_revoked_scope() -> None:
    access = AiAccess(chat_blocked=True)

    assert access.blocks("chat")
    assert not access.blocks("notebooks")
    assert not AiAccess().blocks("chat")


def test_the_revoked_error_is_a_403_with_the_scope_param() -> None:
    error = AiAccessRevokedError(params={"scope": "chat"})

    assert error.code == "ai/access-revoked"
    assert error.status == 403
    assert error.message_key == "ai-access-revoked"
    assert error.params == {"scope": "chat"}


async def test_static_limits_revoke_nothing() -> None:
    provider = StaticLimits(LimitsSettings())

    assert await provider.ai_access(new_id()) == AiAccess()


async def test_effective_limits_read_the_revocation_of_the_snapshot() -> None:
    blocked = new_id()
    other = new_id()
    snapshot = LimitSnapshot(ai_access={blocked: AiAccess(notebooks_blocked=True)})

    async def load() -> LimitSnapshot:
        return snapshot

    provider = EffectiveLimits(LimitsSettings(), load, today=lambda: date(2026, 10, 25))

    assert await provider.ai_access(blocked) == AiAccess(notebooks_blocked=True)
    assert await provider.ai_access(other) == AiAccess()


async def test_a_changed_revocation_is_seen_after_the_cache_expires() -> None:
    user: UUID = new_id()
    state = {"snapshot": LimitSnapshot()}
    now = {"t": 0.0}

    async def load() -> LimitSnapshot:
        return state["snapshot"]

    provider = EffectiveLimits(
        LimitsSettings(),
        load,
        today=lambda: date(2026, 10, 25),
        ttl=30.0,
        monotonic=lambda: now["t"],
    )
    assert await provider.ai_access(user) == AiAccess()

    state["snapshot"] = LimitSnapshot(ai_access={user: AiAccess(chat_blocked=True)})
    now["t"] = 29.0
    assert await provider.ai_access(user) == AiAccess()

    now["t"] = 31.0
    assert await provider.ai_access(user) == AiAccess(chat_blocked=True)
