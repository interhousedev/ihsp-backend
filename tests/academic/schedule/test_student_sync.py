"""A student's full EMIS sync: after a registration and from the settings button."""

import datetime as dt

from app.modules.academic.application.schedule.student_sync_state import SyncState
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.infrastructure.schedule.sync_state import MemorySyncState
from app.shared.actor import Role
from app.shared.base_error import ForbiddenError, RateLimitedError
from app.shared.contracts.emis import EmisUnavailable
from app.shared.contracts.identity import UserRef, UserStatus
from tests.academic.schedule.curriculum_builders import make_curriculum
from tests.academic.schedule.emis_builders import PHYSICS, YULDASHEV, weekly
from tests.academic.schedule.env import Env
from tests.factories import make_actor as build_actor

import pytest


async def _no_term_student(env: Env) -> tuple[Group, UserRef]:
    """A fresh lyceum: no term yet, one group and one registered student."""
    group = await env.group("2TN2", emis_group_id=3292)
    user = await env.student(group)
    env.emis.curriculum_result = make_curriculum()
    env.emis.classes = weekly(2, 0) + weekly(3, 1, subject=PHYSICS, teacher=YULDASHEV)
    return group, user


async def test_the_timetable_alone_gives_up_while_no_term_exists(env: Env) -> None:
    """Root cause: the registration kick ran before any term existed."""
    group, user = await _no_term_student(env)

    result = await env.emis_import.sync_group_timetable.execute(
        group_id=group.id, user_id=user.id
    )

    assert result.status == "no_term"


async def test_the_full_sync_creates_the_term_then_lessons_and_teachers(
    env: Env,
) -> None:
    """The curriculum (and its terms) comes first, so the timetable has a term."""
    _, user = await _no_term_student(env)

    status = await env.emis_import.sync_student_all.execute(user.id, with_marks=False)

    assert status == "synced"
    assert len(await env.lessons()) == 8 + 10  # four weeks ahead, ten since Sep 1
    teachers = [
        u
        for u in env.identity.users.values()
        if u.status is UserStatus.PENDING_ACTIVATION
    ]
    assert sorted(u.last_name for u in teachers) == ["Kalandarova", "Yuldashev"]
    state = await env.emis_import.sync_state.get(user.id)
    assert state is not None
    assert (state.status, state.detail) == ("done", "synced")
    assert state.finished_at == env.clock.now()
    assert env.kicker.names().count("academic.sync_student") == 0


async def test_the_manual_sync_also_refreshes_marks(env: Env) -> None:
    """The settings button asks for the marks and the profile too."""
    _, user = await _no_term_student(env)

    await env.emis_import.sync_student_all.execute(user.id, with_marks=True)

    assert (
        "academic.sync_student",
        {"user_id": str(user.id), "mode": "profile"},
    ) in env.kicker.calls


async def test_an_emis_outage_in_the_curriculum_does_not_stop_the_timetable(
    env: Env,
) -> None:
    """A term made by Administration is enough when EMIS answers no curriculum."""
    _, user = await _no_term_student(env)
    await env.term()
    env.emis.curriculum_error = EmisUnavailable(support_details="down")

    status = await env.emis_import.sync_student_all.execute(user.id, with_marks=False)

    assert status == "synced"


async def test_an_unknown_student_ends_as_failed(env: Env) -> None:
    """Nobody to sync: the state says so instead of staying queued."""
    actor = build_actor(Role.STUDENT)

    status = await env.emis_import.sync_student_all.execute(
        actor.user_id, with_marks=False
    )

    assert status == "no_student"
    state = await env.emis_import.sync_state.get(actor.user_id)
    assert state is not None and state.status == "failed"


# - - - the settings button - - -


async def test_a_request_queues_the_sync_and_kicks_the_task(env: Env) -> None:
    """POST /v1/me/sync: 202 with the queued state; the worker does the rest."""
    actor = build_actor(Role.STUDENT)

    state = await env.emis_import.request_student_sync.execute(actor)

    assert state.status == "queued"
    assert state.requested_at == env.clock.now()
    assert env.kicker.calls[-1] == (
        "academic.sync_student_all",
        {"user_id": str(actor.user_id), "with_marks": True},
    )
    assert await env.emis_import.get_student_sync.execute(actor) == state


async def test_a_second_request_within_ten_minutes_is_rate_limited(env: Env) -> None:
    """Once per ten minutes per student."""
    actor = build_actor(Role.STUDENT)
    await env.emis_import.request_student_sync.execute(actor)

    with pytest.raises(RateLimitedError) as caught:
        await env.emis_import.request_student_sync.execute(actor)

    assert caught.value.params["retry_after"] == 600
    assert env.kicker.names().count("academic.sync_student_all") == 1


async def test_only_students_may_ask_for_a_sync(env: Env) -> None:
    """A teacher has no EMIS student link."""
    with pytest.raises(ForbiddenError):
        await env.emis_import.request_student_sync.execute(build_actor(Role.TEACHER))


async def test_no_sync_yet_reads_as_none(env: Env) -> None:
    """GET /v1/me/sync before any sync."""
    assert (
        await env.emis_import.get_student_sync.execute(build_actor(Role.STUDENT))
        is None
    )


async def test_the_memory_store_claims_a_window_once() -> None:
    """The claim is the rate limit: the second one gets the seconds left."""
    store = MemorySyncState(now=lambda: dt.datetime(2026, 10, 6, tzinfo=dt.UTC))
    user_id = build_actor(Role.STUDENT).user_id

    first = await store.claim(user_id, seconds=600)
    second = await store.claim(user_id, seconds=600)

    assert (first, second) == (None, 600)
    await store.put(
        user_id,
        SyncState("queued", requested_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
    )
    assert (await store.get(user_id)) is not None
