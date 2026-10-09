"""The student's exam calendar: stored controls and control weeks without a date."""

import datetime as dt

from app.modules.academic.application.assessments.inputs import (
    AssessmentInput,
    ProposalInput,
)
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.academic.assessments.conftest import Env

import pytest

D = dt.date.fromisoformat


def _plan(env: Env, day: str, **kwargs: object) -> AssessmentInput:
    fields: dict[str, object] = {
        "subject_id": env.world.math_id,
        "audience": [(env.world.group_id, None)],
        "kind": "midterm",
        "date": D(day),
    }
    fields.update(kwargs)
    return AssessmentInput(**fields)  # type: ignore[arg-type]


async def test_without_any_control_the_weeks_stand_in_for_the_dates(env: Env) -> None:
    """Every curriculum subject shows each control week until a teacher dates it."""
    items = await env.services.list_mine.execute(env.student())

    assert len(items) == 6
    first = items[0]
    assert first["control"] == "midterm_1"
    assert first["has_date"] is False
    assert first["date"] == D("2026-10-19")
    assert first["days_left"] == 13
    assert first["period"] == {"start": D("2026-10-19"), "end": D("2026-10-24")}
    assert (first["kind"], first["status"], first["source"]) == (
        "midterm",
        "planned",
        "admin",
    )
    assert (first["starts_at"], first["lesson_id"], first["room"]) == (None, None, None)
    assert {i["subject"]["short_name"] for i in items} == {"Math", "Fizika"}
    assert [i["date"] for i in items] == sorted(i["date"] for i in items)


async def test_the_subject_name_follows_the_callers_locale(env: Env) -> None:
    """The head student reads Russian: physics has a Russian name."""
    items = await env.services.list_mine.execute(env.head())

    assert "Физика" in {i["subject"]["name"] for i in items}


async def test_the_window_keeps_the_weeks_that_overlap_it(env: Env) -> None:
    """The Today card asks for 14 days: only midterm 1 is that close."""
    items = await env.services.list_mine.execute(
        env.student(), since=D("2026-10-06"), until=D("2026-10-20")
    )

    assert [i["control"] for i in items] == ["midterm_1", "midterm_1"]


async def test_a_running_week_counts_down_to_today(env: Env) -> None:
    """While the week runs the date is today and days_left is zero."""
    env.clock.set(dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.UTC))

    items = await env.services.list_mine.execute(
        env.student(), since=D("2026-10-21"), until=D("2026-10-30")
    )

    assert [(i["control"], i["date"], i["days_left"]) for i in items] == [
        ("midterm_1", D("2026-10-21"), 0),
        ("midterm_1", D("2026-10-21"), 0),
    ]


async def test_a_subject_date_replaces_the_week_for_that_subject(env: Env) -> None:
    """Math has a date; physics still shows the week."""
    await env.services.create.execute(env.teacher(), _plan(env, "2026-10-21"))

    items = await env.services.list_mine.execute(env.student(), until=D("2026-10-25"))

    undated, dated = items  # ordered by date: the week starts on the 19th
    assert (dated["has_date"], dated["date"], dated["control"]) == (
        True,
        D("2026-10-21"),
        "midterm_1",
    )
    assert dated["days_left"] == 15
    assert dated["subject"]["short_name"] == "Math"
    assert dated["period"] == {"start": D("2026-10-19"), "end": D("2026-10-24")}
    assert (undated["has_date"], undated["subject"]["short_name"]) == (False, "Fizika")


async def test_a_cancelled_control_is_hidden_and_its_week_stays_closed(
    env: Env,
) -> None:
    """Cancelling means the control does not happen: no week card replaces it."""
    created = await env.services.create.execute(env.teacher(), _plan(env, "2026-10-21"))
    await env.services.delete.execute(env.teacher(), created["id"])

    items = await env.services.list_mine.execute(env.student(), until=D("2026-10-25"))

    assert [i["subject"]["short_name"] for i in items] == ["Fizika"]


async def test_tentative_controls_are_listed_with_their_status(env: Env) -> None:
    """A head student's suggestion is visible, marked tentative."""
    proposal = await env.services.propose.execute(
        env.head(),
        ProposalInput(
            subject_id=env.world.math_id, kind="midterm", date=D("2026-11-10")
        ),
    )

    items = await env.services.list_mine.execute(
        env.student(), since=D("2026-11-01"), until=D("2026-11-15")
    )

    (item,) = [i for i in items if i["id"] == proposal["id"]]
    assert (item["status"], item["source"]) == ("tentative", "head_student")


async def test_filtering_by_subject(env: Env) -> None:
    """subject_id narrows the stored controls and the weeks."""
    items = await env.services.list_mine.execute(
        env.student(), subject_id=env.world.physics_id
    )

    assert len(items) == 3
    assert {i["subject"]["id"] for i in items} == {env.world.physics_id}


async def test_a_subgroup_control_reaches_only_that_subgroup_and_unset_students(
    env: Env,
) -> None:
    """Students without a subgroup see both subgroups' controls (ACA-2)."""
    created = await env.services.create.execute(
        env.teacher(),
        _plan(env, "2026-10-21", audience=[(env.world.group_id, 2)]),
    )

    def dated(items: list[dict[str, object]]) -> list[object]:
        return [i["id"] for i in items if i["has_date"]]

    assert created["id"] in dated(await env.services.list_mine.execute(env.student()))
    sub = Actor(env.subgroup_id, frozenset({Role.STUDENT}))
    assert created["id"] not in dated(await env.services.list_mine.execute(sub))


async def test_a_user_without_a_student_record_is_refused(env: Env) -> None:
    """Teachers have no calendar of their own."""
    with pytest.raises(StudentNotFoundError):
        await env.services.list_mine.execute(Actor(new_id(), frozenset({Role.STUDENT})))
