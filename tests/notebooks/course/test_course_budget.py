"""LMS-AI 3.3: course staff pay from their own pool, shared with the author assistant.

Calls in a workspace are charged to the acting user, in the `ai:lms` budget keys and
the `lms` output quotas; a student's pools are not touched.
"""

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError
from app.shared.notifications import NotificationDraft

import pytest
from fakeredis.aioredis import FakeRedis


async def _ai_lms_keys(redis: FakeRedis) -> list[str]:
    """The Redis keys of the course pool (`ai:lms:*`)."""
    return sorted([str(key) async for key in redis.scan_iter("ai:lms:*")])


async def test_a_question_in_the_workspace_is_paid_from_the_course_pool(
    services: NotebooksServices,
    workspace: Notebook,
    ws_source: Source,
    editor: Actor,
    settings: Settings,
    redis: FakeRedis,
) -> None:
    """LMS-AI 3.3: the asker's course pool; the student pool stays empty."""
    turn = await services.ask_notebook.execute(editor, workspace.id, "What is F?")

    course = await services.get_usage.execute(editor.user_id, course=True)
    student = await services.get_usage.execute(editor.user_id)
    assert course.day.used > 0 and student.day.used == 0
    # Staff are not limited by the course pool: the calls are counted, never refused.
    assert turn.usage.day.limit is None
    assert turn.usage.session.limit is None
    assert f"ai:lms:day:{editor.user_id}" in " ".join(await _ai_lms_keys(redis))


async def test_the_notebook_usage_shows_the_course_pool(
    services: NotebooksServices,
    workspace: Notebook,
    viewer: Actor,
    settings: Settings,
) -> None:
    """LMS-AI 4: `GET /v1/notebooks/{id}/usage` of a workspace."""
    usage = await services.get_notebook_usage.execute(viewer, workspace.id)

    assert usage.day.limit is None
    assert usage.quotas["artifacts"].limit is None


async def test_course_staff_have_their_own_chat_rate_limit(
    services: NotebooksServices,
    workspace: Notebook,
    ws_source: Source,
    editor: Actor,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LMS-AI 3.3: `lms_ai_chat_per_minute` per acting user."""
    monkeypatch.setattr(settings.limits, "lms_ai_chat_per_minute", 1)
    await services.ask_notebook.execute(editor, workspace.id, "First?")

    with pytest.raises(RateLimitedError):
        await services.ask_notebook.execute(editor, workspace.id, "Second?")


async def test_an_output_is_counted_for_who_asked_in_the_course_quota(
    services: NotebooksServices,
    workspace: Notebook,
    ws_source: Source,
    editor: Actor,
) -> None:
    """LMS-AI 3.3: the course quota of the requester, not the owner's or a pool."""
    await services.request_artifact.execute(
        editor, workspace.id, ArtifactKind.MIND_MAP, {}, None
    )

    course = await services.get_usage.execute(editor.user_id, course=True)
    student = await services.get_usage.execute(editor.user_id)
    assert (course.quotas["artifacts"].used, course.generating) == (1, 1)
    assert (student.quotas["artifacts"].used, student.generating) == (0, 0)


async def test_the_course_quota_is_unlimited_for_staff_but_counted(
    services: NotebooksServices,
    workspace: Notebook,
    ws_source: Source,
    editor: Actor,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Staff have no output cap in a workspace (the `lms_ai_*` quota is not applied)."""
    monkeypatch.setattr(settings.limits, "lms_ai_artifacts_per_day", 1)
    request = services.request_artifact
    await request.execute(editor, workspace.id, ArtifactKind.MIND_MAP, {}, None)
    await request.execute(editor, workspace.id, ArtifactKind.MIND_MAP, {}, None)

    course = await services.get_usage.execute(editor.user_id, course=True)
    assert course.quotas["artifacts"].limit is None
    assert course.quotas["artifacts"].used == 2


async def test_the_job_charges_and_notifies_who_asked(
    services: NotebooksServices,
    uow_factory: UowFactory,
    workspace: Notebook,
    ws_source: Source,
    editor: Actor,
    teacher: Actor,
    outbox: list[NotificationDraft],
) -> None:
    """LMS-AI 3.3: the generation is paid by the requester; the bell is theirs."""
    queued = await services.request_artifact.execute(
        editor, workspace.id, ArtifactKind.MIND_MAP, {}, None
    )

    await services.generate_artifact.execute(queued.id)

    async with uow_factory() as uow:
        done = await uow.artifacts.get(queued.id)
    assert done is not None and done.status is ArtifactStatus.READY
    course = await services.get_usage.execute(editor.user_id, course=True)
    owner = await services.get_usage.execute(teacher.user_id, course=True)
    assert course.day.used > 0 and course.generating == 0
    assert owner.day.used == 0
    assert [draft.user_id for draft in outbox] == [editor.user_id]


async def test_a_canceled_output_gives_the_count_back_to_who_asked(
    services: NotebooksServices,
    workspace: Notebook,
    ws_source: Source,
    editor: Actor,
    teacher: Actor,
) -> None:
    """LMS-AI 3.3: another editor cancels; the requester's quota is freed."""
    queued = await services.request_artifact.execute(
        editor, workspace.id, ArtifactKind.MIND_MAP, {}, None
    )

    await services.cancel_artifact.execute(teacher, workspace.id, queued.id)

    course = await services.get_usage.execute(editor.user_id, course=True)
    assert (course.quotas["artifacts"].used, course.generating) == (0, 0)


async def test_workspace_outputs_skip_the_shared_cache(
    services: NotebooksServices,
    uow_factory: UowFactory,
    workspace: Notebook,
    ws_source: Source,
    editor: Actor,
) -> None:
    """LMS-AI 3.2b: the course context makes a workspace output its own."""
    queued = await services.request_artifact.execute(
        editor, workspace.id, ArtifactKind.MIND_MAP, {}, None
    )

    assert queued.cache_key is None
