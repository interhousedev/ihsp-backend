"""A student's full EMIS sync: after a registration and from the settings button."""

from app.modules.academic.domain.schedule.group import Group
from app.shared.actor import Role
from app.shared.contracts.emis import EmisUnavailable
from app.shared.contracts.identity import UserRef, UserStatus
from tests.academic.schedule.curriculum_builders import make_curriculum
from tests.academic.schedule.emis_builders import PHYSICS, YULDASHEV, weekly
from tests.academic.schedule.env import Env
from tests.factories import make_actor as build_actor


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
    """POST /v1/me/sync: a failed or new job is queued and kicked once."""
    actor = build_actor(Role.STUDENT)

    job = await env.emis_import.request_student_sync.execute(actor)

    assert job.status == "pending"
    assert env.kicker.calls[-1] == (
        "academic.run_student_sync",
        {"user_id": str(actor.user_id)},
    )
    assert await env.emis_import.get_student_sync.execute(actor) == job


async def test_a_second_request_while_pending_is_idempotent(env: Env) -> None:
    """Pressing the button twice queues one sync and returns the same job."""
    actor = build_actor(Role.STUDENT)
    first = await env.emis_import.request_student_sync.execute(actor)

    second = await env.emis_import.request_student_sync.execute(actor)

    assert second == first
    assert env.kicker.names().count("academic.run_student_sync") == 1
