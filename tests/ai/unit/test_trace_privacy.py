"""The masking policy of Langfuse traces and the cached `limit_ai_tracing` read."""

from uuid import UUID, uuid4

from app.modules.ai.domain.trace_privacy import (
    ALWAYS_MASKED,
    OPEN_CHAT_TASKS,
    masks_content,
)
from app.modules.ai.infrastructure.tracing_opt_out import CachedTracingOptOut
from app.shared.ai_tasks import AiTask

import pytest

ESSAY_TASKS = [
    AiTask.ADMIT_ESSAY_REVIEW,
    AiTask.ADMIT_ESSAY_UNI_REVIEW,
    AiTask.ADMIT_ESSAY_COACH,
    AiTask.EXERCISE_FEEDBACK,
]


@pytest.mark.parametrize("task", ESSAY_TASKS)
@pytest.mark.parametrize("limit", [False, True])
@pytest.mark.parametrize("surface", ["web", "telegram", "admission", None])
def test_essays_are_always_masked(task: AiTask, limit: bool, surface: str) -> None:
    assert task.value in ALWAYS_MASKED
    assert masks_content(task.value, surface, limit_tracing=limit) is True


@pytest.mark.parametrize("limit", [False, True])
def test_admission_surface_is_always_masked(limit: bool) -> None:
    assert masks_content(AiTask.EMBEDDING.value, "admission", limit_tracing=limit)


@pytest.mark.parametrize("task", sorted(OPEN_CHAT_TASKS))
@pytest.mark.parametrize("surface", ["web", "telegram"])
def test_general_chat_keeps_text_even_when_limited(task: str, surface: str) -> None:
    assert masks_content(task, surface, limit_tracing=True) is False


@pytest.mark.parametrize(
    ("task", "surface"),
    [
        (AiTask.STUDENT_CHAT.value, "lms"),
        (AiTask.STUDENT_CHAT.value, "notebooks"),
        (AiTask.STUDENT_CHAT.value, None),
        (AiTask.EMBEDDING.value, "web"),
        (None, "web"),
    ],
)
def test_limited_user_masks_everything_else(task: str | None, surface: str) -> None:
    assert masks_content(task, surface, limit_tracing=True) is True
    assert masks_content(task, surface, limit_tracing=False) is False


async def test_opt_out_is_cached_per_user() -> None:
    reads: list[UUID] = []
    clock = [0.0]

    async def load(user_id: UUID) -> bool:
        reads.append(user_id)
        return True

    opt_out = CachedTracingOptOut(load, ttl_seconds=30, now=lambda: clock[0])
    user = uuid4()
    assert await opt_out.limits_tracing(user) is True
    assert await opt_out.limits_tracing(user) is True
    assert reads == [user]
    clock[0] = 31.0
    await opt_out.limits_tracing(user)
    assert reads == [user, user]


async def test_failed_read_masks() -> None:
    async def load(user_id: UUID) -> bool:
        raise RuntimeError("db down")

    assert await CachedTracingOptOut(load).limits_tracing(uuid4()) is True
