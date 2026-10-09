"""Reminders 7, 3 and 1 days before a confirmed control (notify outbox)."""

import datetime as dt
from typing import Any

from app.modules.academic.application.assessments.inputs import AssessmentInput
from app.modules.academic.domain.assessments.edit import AssessmentPatch
from app.shared.notifications import NotificationDraft, NotificationType
from tests.academic.assessments.conftest import Env

D = dt.date.fromisoformat
TODAY = D("2026-10-06")


async def _plan(env: Env, day: str, **kwargs: object) -> dict[str, Any]:
    fields: dict[str, object] = {
        "subject_id": env.world.math_id,
        "audience": [(env.world.group_id, None)],
        "kind": "midterm",
        "date": D(day),
    }
    fields.update(kwargs)
    return await env.services.create.execute(
        env.teacher(), AssessmentInput(**fields)  # type: ignore[arg-type]
    )


def _drafts(env: Env) -> list[NotificationDraft]:
    return [
        d
        for d in env.outbox.notifications
        if d.type == NotificationType.ASSESSMENT_REMINDER
    ]


async def test_a_control_in_seven_days_reminds_every_student_of_the_group(
    env: Env,
) -> None:
    """Three students in the group; each gets one reminder."""
    created = await _plan(env, "2026-10-13", room="204")

    result = await env.services.send_reminders.execute()

    assert result == {"assessments": 1, "notifications": 3}
    users = {d.user_id for d in _drafts(env)}
    assert users == {env.world.user_id, env.head_id, env.subgroup_id}
    draft = next(d for d in _drafts(env) if d.user_id == env.world.user_id)
    assert draft.type == NotificationType.ASSESSMENT_REMINDER
    assert draft.dedupe_key == (
        f"assessment_reminder:{env.world.user_id}:{created['id']}:7"
    )
    assert draft.payload["assessment_id"] == str(created["id"])
    assert draft.payload["days_left"] == 7
    assert draft.payload["date"] == "2026-10-13"
    assert draft.payload["kind"] == "midterm"
    assert draft.payload["room"] == "204"
    assert draft.payload["period_end"] is None


async def test_the_subject_name_follows_each_students_locale(env: Env) -> None:
    """English, Russian and Uzbek readers get their own subject names."""
    await _plan(env, "2026-10-13", subject_id=env.world.physics_id)

    await env.services.send_reminders.execute()

    names = {d.user_id: d.payload["subject_name"] for d in _drafts(env)}
    assert names[env.world.user_id] == "Fizika"  # en falls back to uz
    assert names[env.head_id] == "Физика"
    assert names[env.subgroup_id] == "Fizika"


async def test_only_the_offsets_7_3_and_1_fire(env: Env) -> None:
    """Days 2, 4, 5 and 6 ahead stay silent; 1 and 3 and 7 fire."""
    for day in ("2026-10-07", "2026-10-09", "2026-10-13"):
        await _plan(env, day)
    for day in ("2026-10-08", "2026-10-10", "2026-10-11", "2026-10-12"):
        await _plan(env, day, subject_id=env.world.physics_id)

    result = await env.services.send_reminders.execute()

    assert result["assessments"] == 3
    assert sorted({d.payload["days_left"] for d in _drafts(env)}) == [1, 3, 7]


async def test_running_again_queues_the_same_keys(env: Env) -> None:
    """The outbox ignores a repeated dedupe key, so the keys must repeat exactly."""
    await _plan(env, "2026-10-13")

    await env.services.send_reminders.execute()
    first = {d.dedupe_key for d in _drafts(env)}
    await env.services.send_reminders.execute()
    second = {d.dedupe_key for d in _drafts(env)}

    assert first == second
    assert len(first) == 3


async def test_the_next_day_sends_the_next_offset_under_another_key(env: Env) -> None:
    """The same control is reminded again at 3 days with a different key."""
    await _plan(env, "2026-10-09")
    env.clock.set(dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC))
    await env.services.send_reminders.execute()
    env.clock.set(dt.datetime(2026, 10, 8, 9, 0, tzinfo=dt.UTC))
    await env.services.send_reminders.execute()

    offsets = {d.payload["days_left"] for d in _drafts(env)}
    keys = {d.dedupe_key for d in _drafts(env)}
    assert offsets == {3, 1}
    assert len(keys) == 6


async def test_tentative_and_cancelled_controls_are_not_reminded(env: Env) -> None:
    """A date nobody confirmed may be wrong."""
    created = await _plan(env, "2026-10-13")
    from app.modules.academic.application.assessments.inputs import ProposalInput

    await env.services.propose.execute(
        env.head(),
        ProposalInput(
            subject_id=env.world.physics_id, kind="midterm", date=D("2026-10-13")
        ),
    )
    await env.services.delete.execute(env.teacher(), created["id"])

    result = await env.services.send_reminders.execute()

    assert result == {"assessments": 0, "notifications": 0}
    assert _drafts(env) == []


async def test_confirming_a_suggestion_starts_its_reminders(env: Env) -> None:
    """tentative -> planned: the next run reminds."""
    from app.modules.academic.application.assessments.inputs import ProposalInput

    proposal = await env.services.propose.execute(
        env.head(),
        ProposalInput(
            subject_id=env.world.math_id, kind="midterm", date=D("2026-10-13")
        ),
    )
    await env.services.send_reminders.execute()
    assert _drafts(env) == []

    await env.services.update.execute(
        env.teacher(), proposal["id"], AssessmentPatch(status="planned")
    )
    await env.services.send_reminders.execute()

    assert len(_drafts(env)) == 3


async def test_a_subgroup_control_reminds_that_subgroup_and_unset_students(
    env: Env,
) -> None:
    """Students with no subgroup get both subgroups' reminders; subgroup 1 its own."""
    await _plan(env, "2026-10-13", audience=[(env.world.group_id, 2)])

    await env.services.send_reminders.execute()

    users = {d.user_id for d in _drafts(env)}
    assert users == {env.world.user_id, env.head_id}  # subgroup_id is in subgroup 1


async def test_a_control_week_without_a_subject_date_is_reminded_by_its_start(
    env: Env,
) -> None:
    """Midterm 1 starts on the 19th: reminded on the 12th, 16th and 18th."""
    env.clock.set(dt.datetime(2026, 10, 12, 9, 0, tzinfo=dt.UTC))

    result = await env.services.send_reminders.execute()

    assert result == {"assessments": 2, "notifications": 6}  # 2 subjects x 3 students
    draft = next(d for d in _drafts(env) if d.user_id == env.world.user_id)
    assert draft.payload["control"] == "midterm_1"
    assert draft.payload["date"] == "2026-10-19"
    assert draft.payload["period_end"] == "2026-10-24"
    assert draft.payload["days_left"] == 7
    assert draft.payload["title"] == ""
    assert draft.payload["starts_at"] is None


async def test_a_dated_subject_is_reminded_by_its_date_not_by_the_week(
    env: Env,
) -> None:
    """Math has a date on the 20th; physics still counts down to the 19th."""
    await _plan(env, "2026-10-20")
    env.clock.set(dt.datetime(2026, 10, 12, 9, 0, tzinfo=dt.UTC))

    await env.services.send_reminders.execute()
    by_subject = {
        d.payload["subject_name"]: d.payload["days_left"]
        for d in _drafts(env)
        if d.user_id == env.world.user_id
    }

    assert by_subject == {"Fizika": 7}  # math's date is 8 days away: not today
