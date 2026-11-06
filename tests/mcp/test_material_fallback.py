"""A3: lesson materials, falling back to EMIS when nothing is stored."""

import asyncio
from datetime import timedelta
from typing import Any
from uuid import uuid4

from app.interfaces.mcp.constants import EMIS_FETCH_LIMIT
from app.interfaces.mcp.student import material_wait
from app.shared.contracts.mcp_academic import MaterialFetch
from tests.mcp.conftest import World
from tests.mcp.fakes import make_lesson, make_resource
from tests.mcp.fakes_academic import running
from tests.mcp.helpers import call, data_of, text_of

import pytest

SCOPE = "materials:read"


@pytest.fixture(autouse=True)
def no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """The long-poll does not really sleep."""
    monkeypatch.setattr(material_wait, "POLL_SECONDS", 0)


def _lesson(world: World, user_id: Any = None, **changes: Any) -> Any:
    lesson = make_lesson(id=uuid4(), **changes)
    world.schedule.lessons[lesson.id] = lesson
    if user_id is not None:
        world.schedule.audience.add((user_id, lesson.id))
    return lesson


async def _call(world: World, token: str, lesson: Any, **extra: Any) -> Any:
    async with world.session("student", token) as session:
        return await call(
            session, "get_lesson_materials", lesson_id=str(lesson.id), **extra
        )


async def test_not_in_audience_is_not_found_and_never_asks_emis(world: World) -> None:
    """A3: another group's lesson: not found, no job."""
    token, _ = world.connector_token("student", SCOPE)
    lesson = _lesson(world)
    world.academic_tools.next_fetch = running(world.clock.now())

    result = await _call(world, token, lesson)

    assert result.isError
    assert world.academic_tools.started == []


async def test_stored_materials_are_ready_without_emis(world: World) -> None:
    """A3: resources found locally: no job."""
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id)
    world.links.resources[lesson.id] = [make_resource(lesson_id=lesson.id)]

    data = data_of(await _call(world, token, lesson))

    assert data["status"] == "ready"
    assert len(data["resources"]) == 1
    assert "resources[].title" in data["untrusted_fields"]
    assert world.academic_tools.started == []


async def test_future_and_cancelled_lessons_have_nothing(world: World) -> None:
    """A3: EMIS is not asked about a lesson that did not happen."""
    token, actor = world.connector_token("student", SCOPE)
    today = world.clock.now().date()
    ahead = _lesson(world, actor.user_id, date=today + timedelta(days=3))
    off = _lesson(world, actor.user_id, date=today, status="cancelled")

    assert data_of(await _call(world, token, ahead))["status"] == "none"
    assert data_of(await _call(world, token, off))["status"] == "none"
    assert world.academic_tools.started == []


async def test_in_emis_but_not_stored_returns_the_download_id(world: World) -> None:
    """A3: a running fetch answers pending with its id and the deadline."""
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id, date=world.clock.now().date())
    world.academic_tools.next_fetch = running(world.clock.now())

    data = data_of(await _call(world, token, lesson))

    assert data["status"] == "pending"
    assert data["job_id"] == "a" * 32
    assert data["retry_after_seconds"] == 0
    assert data["deadline_at"]
    assert data["note"]
    assert world.academic_tools.started == [(actor.user_id, lesson.id)]


async def test_the_description_tells_the_client_to_retry_up_to_the_ceiling(
    world: World,
) -> None:
    """A3: the client retries the same call and waits up to 60 seconds."""
    token, _ = world.connector_token("student", SCOPE)
    async with world.session("student", token) as session:
        listed = await session.list_tools()
    text = next(t for t in listed.tools if t.name == "get_lesson_materials").description
    assert text is not None
    assert "pending" in text
    assert "60 seconds" in text
    assert "again" in text


async def test_long_poll_returns_the_files_when_the_job_ends(world: World) -> None:
    """A3: done with files while waiting gives ready in the same call."""
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id, date=world.clock.now().date())
    now = world.clock.now()
    tools = world.academic_tools
    tools.next_fetch = running(now)
    done = MaterialFetch(job_id="a" * 32, status="done", started_at=now)
    tools.script = [
        None,  # type: ignore[list-item] # nothing yet at the first read
        running(now),
        done,
    ]

    original = tools.material_fetch

    async def with_files(lesson_id: Any) -> Any:
        answer = await original(lesson_id)
        if answer is done:
            world.links.resources[lesson.id] = [make_resource(lesson_id=lesson.id)]
        return answer

    tools.material_fetch = with_files  # type: ignore[method-assign]

    data = data_of(await _call(world, token, lesson))

    assert data["status"] == "ready"
    assert len(data["resources"]) == 1


async def test_done_without_files_is_nothing_and_not_asked_again(world: World) -> None:
    """A3: not in EMIS: the kept state is the negative cache."""
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id, date=world.clock.now().date())
    world.academic_tools.fetches[lesson.id] = MaterialFetch(
        job_id="a" * 32, status="done", started_at=world.clock.now()
    )

    data = data_of(await _call(world, token, lesson))

    assert data == {**data, "status": "none", "resources": []}
    assert world.academic_tools.started == []


async def test_past_the_ceiling_is_a_timeout_with_what_exists(world: World) -> None:
    """A3: 60 seconds after the start the client stops waiting."""
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id, date=world.clock.now().date())
    started = world.clock.now() - timedelta(seconds=61)
    world.academic_tools.fetches[lesson.id] = running(started)
    world.links.resources[lesson.id] = [make_resource(lesson_id=lesson.id)]

    data = data_of(await _call(world, token, lesson))

    assert data["status"] == "timeout"
    assert len(data["resources"]) == 1


@pytest.mark.parametrize("reason", ["emis_reauth", "emis_busy"])
async def test_a_failed_fetch_is_unavailable_with_a_fixed_reason(
    world: World, reason: Any
) -> None:
    """A3: failures reach the client as fixed codes."""
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id, date=world.clock.now().date())
    world.academic_tools.fetches[lesson.id] = MaterialFetch(
        job_id="a" * 32, status="failed", started_at=world.clock.now(), reason=reason
    )

    data = data_of(await _call(world, token, lesson))

    assert data["status"] == "unavailable"
    assert data["reason"] == reason


async def test_a_foreign_job_id_is_ignored(world: World) -> None:
    """A3: state comes from the lesson; a made-up id reads nothing of anyone else."""
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id, date=world.clock.now().date())
    world.academic_tools.fetches[lesson.id] = running(world.clock.now())

    data = data_of(await _call(world, token, lesson, job_id=str(uuid4())))

    assert data["job_id"] == "a" * 32


async def test_only_a_new_fetch_spends_the_emis_limit(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A3: polling a running job is not charged; starting a new one is."""
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id, date=world.clock.now().date())
    world.academic_tools.next_fetch = running(world.clock.now())
    key = f"{EMIS_FETCH_LIMIT.name}:{actor.user_id}"
    hits: list[str] = []
    limiter_hit = world.deps().rate_limiter.__class__.hit

    async def spy(self: Any, name: str, **kwargs: Any) -> Any:
        hits.append(name)
        return await limiter_hit(self, name, **kwargs)

    monkeypatch.setattr(world.deps().rate_limiter.__class__, "hit", spy)

    async with world.session("student", token) as session:
        for _ in range(3):
            data_of(
                await call(session, "get_lesson_materials", lesson_id=str(lesson.id))
            )

    assert sum(name.endswith(key) for name in hits) == 1


async def test_the_emis_limit_refuses_a_new_fetch(world: World) -> None:
    """A3: over the hourly class: refused, nothing started."""
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id, date=world.clock.now().date())
    world.academic_tools.next_fetch = running(world.clock.now())
    limiter = world.deps().rate_limiter
    for _ in range(EMIS_FETCH_LIMIT.limit):
        await limiter.hit(
            f"mcp:{EMIS_FETCH_LIMIT.name}:{actor.user_id}",
            limit=EMIS_FETCH_LIMIT.limit,
            window_seconds=EMIS_FETCH_LIMIT.window_seconds,
        )

    result = await _call(world, token, lesson)

    assert result.isError, text_of(result)
    assert world.academic_tools.started == []


async def test_a_full_process_answers_pending_at_once(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A3: above the long-poll limit the client gets pending without waiting."""
    monkeypatch.setattr(material_wait, "_gate", asyncio.Semaphore(0))
    token, actor = world.connector_token("student", SCOPE)
    lesson = _lesson(world, actor.user_id, date=world.clock.now().date())
    world.academic_tools.fetches[lesson.id] = running(world.clock.now())
    reads: list[Any] = []
    original = world.academic_tools.material_fetch

    async def counting(lesson_id: Any) -> Any:
        reads.append(lesson_id)
        return await original(lesson_id)

    world.academic_tools.material_fetch = counting  # type: ignore[method-assign]

    data = data_of(await _call(world, token, lesson))

    assert data["status"] == "pending"
    assert len(reads) == 1
