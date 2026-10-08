"""Syncing one student against a scripted EMIS (SYNC-3 to SYNC-9, ACA-14, ACA-22)."""

import datetime as dt
from dataclasses import replace
from decimal import Decimal

from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisProfile,
    EmisSubject,
    EmisUnavailable,
)
from app.shared.contracts.identity import UserPreferences
from app.shared.notifications import NotificationType
from tests.academic.marks.conftest import Env
from tests.academic.marks.db import marks_of, result_of, student_of
from tests.academic.marks.fakes.emis import make_ratings
from tests.academic.marks.fakes.identity import make_user
from tests.academic.marks.world import DAY, MATH_EMIS, PHYSICS_EMIS

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]
OTHER_DAY = dt.date(2026, 10, 7)


def _types(env: Env) -> list[NotificationType]:
    return [d.type for d in env.outbox.notifications]


async def test_new_marks_are_stored_matched_and_announced(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """New marks get the earliest lesson (ACA-14), results follow, one `marks` draft."""
    w = env.world
    env.emis.set(
        make_ratings(
            MATH_EMIS,
            3,
            [("lesson", DAY, 5), ("lesson", DAY, 4), ("lesson", OTHER_DAY, 5)],
            rating=91,
        )
    )
    outcome = await env.sync.execute(w.user_id)

    assert outcome.status == "ok"
    rows = await marks_of(sessionmaker_in_tx, w.user_id)
    assert len(rows) == 3
    on_day = [r for r in rows if r.date == DAY]
    assert {r.lesson_id for r in on_day} == {
        w.math_lesson_1
    }  # double period: the first
    assert [r.lesson_id for r in rows if r.date == OTHER_DAY] == [None]

    math = await result_of(sessionmaker_in_tx, w.user_id, 3, w.math_id)
    assert (math.lesson_avg, math.value, math.marks_count, math.emis_rating) == (
        Decimal("4.67"),
        Decimal("4.67"),
        3,
        91,
    )
    gpa = await result_of(sessionmaker_in_tx, w.user_id, 3, None)
    assert gpa.value == Decimal("4.67")

    assert _types(env) == [NotificationType.MARKS]
    draft = env.outbox.notifications[0]
    assert {m["value"] for m in draft.payload["marks"]} == {5, 4}
    assert draft.payload["marks"][0]["subject_name"] == "Mathematics"
    student = await student_of(sessionmaker_in_tx, w.user_id)
    assert student.synced_at == env.clock.now()
    assert student.sync_failures == 0


async def test_unchanged_response_is_skipped(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """SYNC-6: the same hash again writes nothing and notifies nobody."""
    env.emis.set(make_ratings(MATH_EMIS, 3, [("lesson", DAY, 5)]))
    await env.sync.execute(env.world.user_id)
    env.outbox.notifications.clear()
    before = await marks_of(sessionmaker_in_tx, env.world.user_id)

    await env.sync.execute(env.world.user_id)

    after = await marks_of(sessionmaker_in_tx, env.world.user_id)
    assert [m.id for m in after] == [m.id for m in before]
    assert [m.updated_at for m in after] == [m.updated_at for m in before]
    assert env.outbox.notifications == []


async def test_marks_notification_follows_the_students_settings(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """A mark outside the chosen values is stored but not announced."""
    env.identity.prefs[env.world.user_id] = UserPreferences(marks_values=[5])
    env.emis.set(make_ratings(MATH_EMIS, 3, [("lesson", DAY, 4)]))

    await env.sync.execute(env.world.user_id)

    assert len(await marks_of(sessionmaker_in_tx, env.world.user_id)) == 1
    assert env.outbox.notifications == []


async def test_identical_marks_removed_and_restored_silently(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """SYNC-5: [5,5] -> [5] removes ordinal 2 silently; [5,5] again restores it."""
    uid = env.world.user_id
    env.emis.set(make_ratings(MATH_EMIS, 3, [("lesson", DAY, 5), ("lesson", DAY, 5)]))
    await env.sync.execute(uid)
    assert [
        (m.ordinal, m.removed_at) for m in await marks_of(sessionmaker_in_tx, uid)
    ] == [
        (1, None),
        (2, None),
    ]
    assert len(env.outbox.notifications) == 1

    env.emis.set(make_ratings(MATH_EMIS, 3, [("lesson", DAY, 5)]))
    await env.sync.execute(uid)
    rows = await marks_of(sessionmaker_in_tx, uid)
    assert rows[0].removed_at is None
    assert rows[1].removed_at == env.clock.now()
    math = await result_of(sessionmaker_in_tx, uid, 3, env.world.math_id)
    assert math.marks_count == 1

    env.emis.set(make_ratings(MATH_EMIS, 3, [("lesson", DAY, 5), ("lesson", DAY, 5)]))
    await env.sync.execute(uid)
    rows = await marks_of(sessionmaker_in_tx, uid)
    assert [m.removed_at for m in rows] == [None, None]
    assert len(env.outbox.notifications) == 1  # nothing new was announced


async def test_backfill_is_silent_and_finishes_the_import(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """SYNC-4: no backfilled_at: all four semesters are imported, no messages."""
    from tests.academic.marks.world import add_student

    uid = await add_student(sessionmaker_in_tx, env.world, backfilled=False)
    env.identity.add(make_user(uid))
    env.enrollment.ref = env.enrollment.ref.__class__(
        user_id=uid,
        group_id=env.world.group_id,
        group_name="2TN2",
        subgroup=None,
        status="active",
        synced_at=None,
    )
    env.emis.profile_result = EmisProfile(
        1, "Aliya", "Karimova", None, 10815, 3292, "2TN2", 3, 77
    )
    env.emis.subjects_result = [
        EmisSubject(MATH_EMIS, "Matematika", "Математика", "Mathematics")
    ]
    env.emis.set(make_ratings(MATH_EMIS, 1, [("lesson", dt.date(2025, 10, 1), 3)]))
    env.emis.set(make_ratings(MATH_EMIS, 3, [("lesson", DAY, 5)]))

    outcome = await env.sync.execute(uid)  # mode "regular" is turned into a backfill

    assert outcome.status == "ok"
    assert env.outbox.notifications == []
    assert {m.semester for m in await marks_of(sessionmaker_in_tx, uid)} == {1, 3}
    requested = {(s, m) for name, s, m in env.emis.calls if name == "ratings"}
    assert requested == {
        (e, sem) for e in (MATH_EMIS, PHYSICS_EMIS) for sem in (1, 2, 3, 4)
    }
    student = await student_of(sessionmaker_in_tx, uid)
    assert student.backfilled_at == env.clock.now()
    assert student.profile_synced_at == env.clock.now()
    assert env.enrollment.ensured[0]["group_emis_id"] == 3292
    assert env.commands.name_updates[0][1]["last_name"] == "Karimova"


async def test_auth_failure_notifies_once_a_day_and_counts(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """SYNC-8: EMIS rejects the login: `emis_reauth` with a per-day dedupe key."""
    uid = env.world.user_id
    env.emis.error = EmisAuthFailed()

    first = await env.sync.execute(uid)
    second = await env.sync.execute(uid)
    env.clock.advance(hours=24)
    await env.sync.execute(uid)

    assert first.status == second.status == "reauth"
    keys = [d.dedupe_key for d in env.outbox.notifications]
    assert keys[0] == keys[1] == f"emis-reauth:{uid}:2026-10-06"
    assert keys[2] == f"emis-reauth:{uid}:2026-10-07"
    assert all(d.type == NotificationType.EMIS_REAUTH for d in env.outbox.notifications)
    student = await student_of(sessionmaker_in_tx, uid)
    assert student.sync_failures == 3
    assert student.sync_error == "emis-auth-failed"


async def test_students_needing_reauth_are_not_synced(env: Env) -> None:
    """A link in needs_reauth is skipped without calling EMIS."""
    env.identity.add(make_user(env.world.user_id, emis_status="needs_reauth"))

    outcome = await env.sync.execute(env.world.user_id)

    assert outcome.status == "skipped"
    assert env.emis.calls == []


async def test_emis_outage_is_counted_and_reraised(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """EMIS down: the failure is counted, nothing is sent, the error is raised."""
    env.emis.error = EmisUnavailable()

    with pytest.raises(EmisUnavailable):
        await env.sync.execute(env.world.user_id)

    student = await student_of(sessionmaker_in_tx, env.world.user_id)
    assert student.sync_failures == 1
    assert student.sync_error is not None and "emis/unavailable" in student.sync_error
    assert env.outbox.notifications == []


async def test_profile_run_applies_a_new_group(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """SYNC-3, SYNC-9: the 20:00 run refreshes group, names and subjects."""
    env.emis.profile_result = EmisProfile(
        1, "Aliya", "Karimova", "Ravshanovna", 10815, 3300, "3TN1", 4, 88
    )
    env.emis.subjects_result = [
        EmisSubject(MATH_EMIS, "Matematika", "Математика", "Mathematics")
    ]

    outcome = await env.sync.execute(env.world.user_id, mode="profile")

    assert outcome.status == "ok"
    ensured = env.enrollment.ensured[0]
    assert (ensured["group_emis_id"], ensured["group_name"]) == (3300, "3TN1")
    assert (ensured["current_semester"], ensured["curriculum_id"]) == (4, 88)
    assert env.commands.name_updates[0][1]["middle_name"] == "Ravshanovna"
    assert env.enrollment.synced_subjects[0][0] == env.world.group_id
    student = await student_of(sessionmaker_in_tx, env.world.user_id)
    assert student.profile_synced_at == env.clock.now()


async def test_profile_run_asks_for_the_timetable_of_a_group_without_one(
    env: Env,
) -> None:
    """ACA-1: a student who moved to an unknown group starts the import."""
    env.enrollment.ref = replace(env.enrollment.ref, needs_timetable=True)
    env.emis.profile_result = EmisProfile(
        1, "Aliya", "Karimova", None, 10815, 3300, "3TN1", 4, 88
    )

    await env.sync.execute(env.world.user_id, mode="profile")

    assert env.kicker.calls == [
        (
            "academic.bootstrap_group",
            {
                "user_id": str(env.world.user_id),
                "group_id": str(env.enrollment.ref.group_id),
            },
        )
    ]


async def test_profile_run_leaves_a_group_with_a_timetable_alone(env: Env) -> None:
    """ACA-1: no task for a group that already has its lessons."""
    env.emis.profile_result = EmisProfile(
        1, "Aliya", "Karimova", None, 10815, 3292, "2TN2", 3, 1
    )

    await env.sync.execute(env.world.user_id, mode="profile")

    assert env.kicker.calls == []


async def test_a_backfill_does_not_start_the_import_the_registration_did(
    env: Env,
) -> None:
    """ACA-1: registration kicked bootstrap_group itself; the backfill only syncs."""
    env.enrollment.ref = replace(env.enrollment.ref, needs_timetable=True)
    env.emis.profile_result = EmisProfile(
        1, "Aliya", "Karimova", None, 10815, 3292, "2TN2", 3, 1
    )

    await env.sync.execute(env.world.user_id, mode="backfill")

    assert env.kicker.calls == []


async def test_other_institution_marks_the_student_as_left(env: Env) -> None:
    """The profile belongs to another institution: mark_left and stop."""
    env.emis.profile_result = EmisProfile(1, "A", "B", None, 999, 3292, "2TN2", 3, 1)

    outcome = await env.sync.execute(env.world.user_id, mode="profile")

    assert outcome.status == "left"
    assert env.enrollment.left == [(env.world.user_id, "institution")]
    assert env.emis.ratings_calls() == 0


async def test_drops_and_the_formula_switch(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """ACA-22: no drop alert for a formula switch; real drops do alert."""
    uid, math = env.world.user_id, env.world.math_id
    base = [("lesson", DAY, 5), ("lesson", DAY, 4), ("midterm", DAY, 3)]
    env.emis.set(make_ratings(MATH_EMIS, 3, base))
    await env.sync.execute(uid)
    assert (await result_of(sessionmaker_in_tx, uid, 3, math)).value == Decimal("4.50")
    env.outbox.notifications.clear()

    # The final appears: 4.50 -> 4.17 only because of the formula (and GPA rises).
    env.emis.set(make_ratings(MATH_EMIS, 3, [*base, ("final", DAY, 5)]))
    await env.sync.execute(uid)
    assert (await result_of(sessionmaker_in_tx, uid, 3, math)).value == Decimal("4.17")
    assert _types(env) == [NotificationType.MARKS]
    env.outbox.notifications.clear()

    # A real fall: a 2 under the same formula, GPA 4.25 -> 3.80.
    env.emis.set(
        make_ratings(MATH_EMIS, 3, [*base, ("final", DAY, 5), ("lesson", OTHER_DAY, 2)])
    )
    await env.sync.execute(uid)
    drops = [
        d for d in env.outbox.notifications if d.type == NotificationType.RESULT_DROP
    ]
    assert {d.payload["scope"] for d in drops} == {"gpa", "subject"}
    gpa = next(d for d in drops if d.payload["scope"] == "gpa")
    assert (gpa.payload["old"], gpa.payload["new"]) == (4.25, 3.8)
    subject = next(d for d in drops if d.payload["scope"] == "subject")
    assert subject.payload["subject_name"] == "Mathematics"
    assert (subject.payload["old"], subject.payload["new"]) == (4.17, 3.89)


async def test_curriculum_subjects_without_emis_id_are_skipped(env: Env) -> None:
    """Only subjects with an EMIS id are requested, once per semester."""
    await env.sync.execute(env.world.user_id)

    assert sorted((s, m) for name, s, m in env.emis.calls if name == "ratings") == [
        (MATH_EMIS, 3),
        (PHYSICS_EMIS, 3),
    ]
