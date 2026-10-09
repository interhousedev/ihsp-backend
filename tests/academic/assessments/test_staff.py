"""Teachers and Administration plan, confirm, edit and dismiss controls."""

import datetime as dt
from typing import Any
from uuid import uuid4

from app.modules.academic.application.assessments.inputs import (
    AssessmentInput,
    ProposalInput,
    StaffFilters,
)
from app.modules.academic.domain.assessments.edit import AssessmentPatch
from app.modules.academic.domain.assessments.errors import (
    AssessmentExistsError,
    AssessmentNotFoundError,
    AssessmentSubjectNotFoundError,
    InvalidAssessmentError,
    NotAssessmentTeacherError,
    NotHeadStudentError,
)
from tests.academic.assessments.conftest import Env, add_exam_lesson

import pytest

D = dt.date.fromisoformat


def _input(env: Env, day: str = "2026-10-21", **kwargs: object) -> AssessmentInput:
    fields: dict[str, object] = {
        "subject_id": env.world.math_id,
        "audience": [(env.world.group_id, None)],
        "kind": "midterm",
        "date": D(day),
    }
    fields.update(kwargs)
    return AssessmentInput(**fields)  # type: ignore[arg-type]


def _proposal(env: Env, day: str = "2026-11-10", **kwargs: object) -> ProposalInput:
    fields: dict[str, object] = {
        "subject_id": env.world.math_id,
        "kind": "midterm",
        "date": D(day),
    }
    fields.update(kwargs)
    return ProposalInput(**fields)  # type: ignore[arg-type]


async def test_a_teacher_plans_a_control_for_a_group_they_teach(env: Env) -> None:
    """The control is planned, from the teacher, and knows its control week."""
    item = await env.services.create.execute(
        env.teacher(),
        _input(
            env,
            title="  Algebra  ",
            room="204",
            note="Bring a ruler",
            starts_at=dt.datetime(2026, 10, 21, 4, 0, tzinfo=dt.UTC),
        ),
    )

    assert (item["status"], item["source"], item["kind"]) == (
        "planned",
        "teacher",
        "midterm",
    )
    assert (item["title"], item["room"], item["note"]) == (
        "Algebra",
        "204",
        "Bring a ruler",
    )
    assert (item["control"], item["has_date"], item["days_left"]) == (
        "midterm_1",
        True,
        15,
    )
    assert item["subject"]["short_name"] == "Math"
    assert item["audience"] == [
        {"group_id": env.world.group_id, "group_name": "2TN2", "subgroup": None}
    ]
    assert item["created_by"]["id"] == env.world.teacher_id
    assert env.outbox.audits[-1].type == "assessment.created"


async def test_administration_plans_a_control_for_any_group(env: Env) -> None:
    """The admin need not teach the subject; the source says admin."""
    item = await env.services.create.execute(
        env.admin(), _input(env, "2026-12-15", kind="final")
    )

    assert (item["source"], item["status"], item["control"]) == (
        "admin",
        "planned",
        "final",
    )


async def test_a_control_week_can_be_named_for_the_new_control(env: Env) -> None:
    """The second midterm, although the date is nearer to the first week."""
    item = await env.services.create.execute(
        env.teacher(), _input(env, "2026-10-28", control="midterm_2")
    )

    assert item["control"] == "midterm_2"


async def test_a_midterm_cannot_be_the_final_week(env: Env) -> None:
    """The named week must match the kind."""
    with pytest.raises(InvalidAssessmentError):
        await env.services.create.execute(env.teacher(), _input(env, control="final"))


async def test_a_teacher_who_does_not_teach_the_subject_in_the_group_is_refused(
    env: Env,
) -> None:
    """403 for a stranger; nothing is stored."""
    with pytest.raises(NotAssessmentTeacherError):
        await env.services.create.execute(env.stranger(), _input(env))

    assert await env.services.list_staff.execute(env.admin(), StaffFilters()) == []


async def test_a_student_cannot_plan_a_control(env: Env) -> None:
    """Only teachers and Administration."""
    with pytest.raises(NotAssessmentTeacherError):
        await env.services.create.execute(env.student(), _input(env))


@pytest.mark.parametrize(
    "bad",
    [
        {"audience": []},
        {"audience": [(uuid4(), None)]},
        {"title": "x" * 201},
        {"starts_at": dt.datetime(2026, 10, 22, 4, 0, tzinfo=dt.UTC)},
    ],
    ids=["no-audience", "unknown-group", "long-title", "time-on-another-day"],
)
async def test_invalid_controls_are_refused(env: Env, bad: dict[str, Any]) -> None:
    """The audience, the title and the start time are checked."""
    with pytest.raises(InvalidAssessmentError):
        await env.services.create.execute(env.admin(), _input(env, **bad))


async def test_an_unknown_subject_is_refused(env: Env) -> None:
    """The subject must exist."""
    with pytest.raises(AssessmentSubjectNotFoundError):
        await env.services.create.execute(env.admin(), _input(env, subject_id=uuid4()))


async def test_a_linked_lesson_must_be_of_the_same_subject(env: Env) -> None:
    """lesson_id of another subject is invalid; of the same subject it is kept."""
    with pytest.raises(InvalidAssessmentError):
        await env.services.create.execute(
            env.admin(), _input(env, lesson_id=env.world.physics_lesson)
        )

    item = await env.services.create.execute(
        env.admin(), _input(env, lesson_id=env.world.math_lesson_1)
    )

    assert item["lesson_id"] == env.world.math_lesson_1


async def test_an_emis_suggestion_is_confirmed_by_a_teacher(env: Env) -> None:
    """tentative -> planned with status planned, nothing else changed."""
    await add_exam_lesson(env, D("2026-11-10"))
    await env.services.generate_suggestions.execute()
    (suggested,) = await env.services.list_staff.execute(
        env.teacher(), StaffFilters(status="tentative")
    )

    confirmed = await env.services.update.execute(
        env.teacher(), suggested["id"], AssessmentPatch(status="planned")
    )

    assert (confirmed["status"], confirmed["source"]) == ("planned", "emis")
    assert confirmed["date"] == suggested["date"]


async def test_editing_a_suggestion_confirms_it_with_the_new_values(env: Env) -> None:
    """Fixing the date or the room vouches for the control."""
    await add_exam_lesson(env, D("2026-11-10"))
    await env.services.generate_suggestions.execute()
    (suggested,) = await env.services.list_staff.execute(
        env.teacher(), StaffFilters(status="tentative")
    )

    edited = await env.services.update.execute(
        env.teacher(),
        suggested["id"],
        AssessmentPatch(date=D("2026-11-24"), room="305"),
    )

    assert (edited["status"], edited["date"], edited["room"]) == (
        "planned",
        D("2026-11-24"),
        "305",
    )
    assert edited["control"] == "midterm_2"
    assert env.outbox.audits[-1].type == "assessment.updated"


async def test_a_teacher_can_clear_the_optional_fields(env: Env) -> None:
    """null clears the room and the note."""
    created = await env.services.create.execute(
        env.teacher(), _input(env, room="204", note="x")
    )

    cleared = await env.services.update.execute(
        env.teacher(), created["id"], AssessmentPatch(room=None, note=None)
    )

    assert (cleared["room"], cleared["note"]) == (None, None)


async def test_dismissing_a_suggestion_keeps_it_from_coming_back(env: Env) -> None:
    """DELETE cancels; the next generator run does not suggest it again."""
    await add_exam_lesson(env, D("2026-11-10"))
    await env.services.generate_suggestions.execute()
    (suggested,) = await env.services.list_staff.execute(
        env.teacher(), StaffFilters(status="tentative")
    )

    await env.services.delete.execute(env.teacher(), suggested["id"])
    again = await env.services.generate_suggestions.execute()

    assert again["created"] == 0
    assert await env.services.list_staff.execute(env.teacher(), StaffFilters()) == []
    (gone,) = await env.services.list_staff.execute(
        env.teacher(), StaffFilters(status="cancelled")
    )
    assert gone["id"] == suggested["id"]
    assert env.outbox.audits[-1].type == "assessment.cancelled"


async def test_cancelling_twice_is_not_an_error(env: Env) -> None:
    """DELETE is idempotent."""
    created = await env.services.create.execute(env.teacher(), _input(env))

    await env.services.delete.execute(env.teacher(), created["id"])
    await env.services.delete.execute(env.teacher(), created["id"])

    audits = [a for a in env.outbox.audits if a.type == "assessment.cancelled"]
    assert len(audits) == 1


async def test_a_cancelled_control_can_be_restored(env: Env) -> None:
    """status planned brings it back."""
    created = await env.services.create.execute(env.teacher(), _input(env))
    await env.services.delete.execute(env.teacher(), created["id"])

    restored = await env.services.update.execute(
        env.teacher(), created["id"], AssessmentPatch(status="planned")
    )

    assert restored["status"] == "planned"


async def test_only_a_teacher_of_the_subject_edits_or_cancels(env: Env) -> None:
    """A stranger gets 403; an unknown id is 404."""
    created = await env.services.create.execute(env.teacher(), _input(env))

    with pytest.raises(NotAssessmentTeacherError):
        await env.services.update.execute(
            env.stranger(), created["id"], AssessmentPatch(room="1")
        )
    with pytest.raises(NotAssessmentTeacherError):
        await env.services.delete.execute(env.stranger(), created["id"])
    with pytest.raises(AssessmentNotFoundError):
        await env.services.update.execute(env.admin(), uuid4(), AssessmentPatch())
    with pytest.raises(AssessmentNotFoundError):
        await env.services.delete.execute(env.admin(), uuid4())


async def test_moving_a_control_to_another_subject_needs_that_subject_too(
    env: Env,
) -> None:
    """The teacher of math and physics may; the checks run on the new subject."""
    created = await env.services.create.execute(env.teacher(), _input(env))
    moved = await env.services.update.execute(
        env.teacher(), created["id"], AssessmentPatch(subject_id=env.world.physics_id)
    )
    assert moved["subject"]["id"] == env.world.physics_id

    with pytest.raises(AssessmentSubjectNotFoundError):
        await env.services.update.execute(
            env.admin(), created["id"], AssessmentPatch(subject_id=uuid4())
        )


async def test_a_teacher_lists_only_what_they_teach(env: Env) -> None:
    """Admin sees everything; a stranger sees nothing."""
    await env.services.create.execute(env.admin(), _input(env))

    mine = await env.services.list_staff.execute(env.teacher(), StaffFilters())
    nothing = await env.services.list_staff.execute(env.stranger(), StaffFilters())
    admin = await env.services.list_staff.execute(
        env.admin(), StaffFilters(), everything=True
    )

    assert len(mine) == len(admin) == 1
    assert nothing == []


async def test_staff_filters(env: Env) -> None:
    """Subject, kind, source, status, group and dates narrow the list."""
    await env.services.create.execute(env.teacher(), _input(env, "2026-10-21"))
    await env.services.create.execute(
        env.admin(),
        _input(
            env,
            "2026-12-15",
            kind="final",
            subject_id=env.world.physics_id,
        ),
    )

    async def ids(**kw: object) -> int:
        got = await env.services.list_staff.execute(
            env.admin(), StaffFilters(**kw), everything=True  # type: ignore[arg-type]
        )
        return len(got)

    assert await ids() == 2
    assert await ids(kind="final") == 1
    assert await ids(subject_id=env.world.math_id) == 1
    assert await ids(source="admin") == 1
    assert await ids(status="tentative") == 0
    assert await ids(group_id=env.world.group_id) == 2
    assert await ids(group_id=uuid4()) == 0
    assert await ids(since=D("2026-11-01")) == 1
    assert await ids(until=D("2026-11-01")) == 1


async def test_undated_weeks_are_listed_for_staff_when_asked(env: Env) -> None:
    """A teacher sees the weeks of the subjects they teach that still need a date."""
    created = await env.services.create.execute(
        env.teacher(), _input(env, "2026-10-21")
    )

    items = await env.services.list_staff.execute(
        env.teacher(), StaffFilters(undated=True)
    )

    undated = [i for i in items if not i["has_date"]]
    assert len(undated) == 5  # 2 subjects x 3 weeks, minus math midterm 1
    assert all(i["created_by"] is None and i["created_at"] is None for i in undated)
    assert undated[0]["audience"][0]["group_name"] == "2TN2"
    assert created["id"] in [i["id"] for i in items]
    stranger = await env.services.list_staff.execute(
        env.stranger(), StaffFilters(undated=True)
    )
    assert stranger == []
    tentative_only = await env.services.list_staff.execute(
        env.teacher(), StaffFilters(undated=True, status="tentative")
    )
    assert tentative_only == []


async def test_a_head_student_suggests_a_date_for_their_group(env: Env) -> None:
    """The suggestion is tentative, from the head student, for the whole group."""
    item = await env.services.propose.execute(
        env.head(), _proposal(env, note="Maybe the 10th")
    )

    assert (item["status"], item["source"], item["note"]) == (
        "tentative",
        "head_student",
        "Maybe the 10th",
    )
    assert item["control"] == "midterm_2"
    assert env.outbox.audits[-1].type == "assessment.proposed"
    (staff,) = await env.services.list_staff.execute(
        env.teacher(), StaffFilters(status="tentative")
    )
    assert staff["audience"][0]["subgroup"] is None
    assert staff["created_by"]["id"] == env.head_id


async def test_other_students_cannot_suggest_dates(env: Env) -> None:
    """Only the head student of the group."""
    with pytest.raises(NotHeadStudentError):
        await env.services.propose.execute(env.student(), _proposal(env))


async def test_a_suggestion_for_a_known_control_is_a_conflict(env: Env) -> None:
    """A control of the same subject and week already exists for the group."""
    await env.services.create.execute(env.teacher(), _input(env, "2026-11-12"))

    with pytest.raises(AssessmentExistsError):
        await env.services.propose.execute(env.head(), _proposal(env, "2026-11-10"))


async def test_a_suggestion_for_an_unknown_subject_is_refused(env: Env) -> None:
    """The subject must exist."""
    with pytest.raises(AssessmentSubjectNotFoundError):
        await env.services.propose.execute(
            env.head(), _proposal(env, subject_id=uuid4())
        )
