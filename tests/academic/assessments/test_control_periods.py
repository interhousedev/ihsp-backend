"""GET /v1/me/academic/control-periods: exams left and marks taken per control week."""

import datetime as dt
from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_assessments import ROUTERS as ME_ROUTERS
from app.modules.academic.application.assessments.inputs import AssessmentInput
from app.modules.academic.infrastructure.orm.mark import Mark
from app.shared.ids import new_id
from tests.academic.assessments.conftest import Env

D = dt.date.fromisoformat


async def _plan(env: Env, subject_id: Any, day: str) -> None:
    await env.services.create.execute(
        env.teacher(),
        AssessmentInput(
            subject_id=subject_id,
            audience=[(env.world.group_id, None)],
            kind="midterm",
            date=D(day),
        ),
    )


async def _mark(env: Env, subject_id: Any, day: str, value: int) -> None:
    async with env.maker() as session:
        session.add(
            Mark(
                id=new_id(),
                student_id=env.world.user_id,
                subject_id=subject_id,
                semester=1,
                type="midterm",
                value=value,
                date=D(day),
                ordinal=1,
            )
        )
        await session.commit()


async def test_a_period_lists_upcoming_and_taken_exams(env: Env) -> None:
    """A marked exam and a passed unmarked one are taken; a dated future one is left."""
    await _plan(env, env.world.math_id, "2026-10-20")
    await _plan(env, env.world.physics_id, "2026-10-22")
    await _mark(env, env.world.math_id, "2026-10-20", 5)
    env.clock.set(dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.UTC))

    periods = await env.services.list_control_periods.execute(env.student())

    first = periods[0]
    assert (first["control"], first["start"], first["end"]) == (
        "midterm_1",
        D("2026-10-19"),
        D("2026-10-24"),
    )
    by_subject = {e["subject"]["short_name"]: e for e in first["exams"]}
    assert (by_subject["Math"]["state"], by_subject["Math"]["mark"]) == ("taken", 5)
    assert (by_subject["Fizika"]["state"], by_subject["Fizika"]["mark"]) == (
        "upcoming",
        None,
    )
    assert [p["control"] for p in periods] == ["midterm_1", "midterm_2", "final"]


async def test_a_passed_exam_without_a_mark_has_no_mark(env: Env) -> None:
    """The date is behind: taken, mark null."""
    await _plan(env, env.world.math_id, "2026-10-20")
    env.clock.set(dt.datetime(2026, 10, 22, 9, 0, tzinfo=dt.UTC))

    periods = await env.services.list_control_periods.execute(env.student())

    math = next(e for e in periods[0]["exams"] if e["subject"]["short_name"] == "Math")
    assert (math["state"], math["mark"]) == ("taken", None)


async def test_the_route_gives_the_documented_shape(http_client: Any, env: Env) -> None:
    """Students get {items}; teachers get 403."""
    await _plan(env, env.world.math_id, "2026-10-20")
    actor = env.student()
    client = await http_client(
        ME_ROUTERS,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(assessments=env.services),
    )

    response = await client.get("/v1/me/academic/control-periods")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert set(item) == {"control", "kind", "start", "end", "exams"}
    assert set(item["exams"][0]) == {
        "subject",
        "date",
        "starts_at",
        "room",
        "status",
        "state",
        "mark",
    }
    teacher = env.teacher()
    other = await http_client(
        ME_ROUTERS,
        {get_actor: lambda: teacher},
        academic=SimpleNamespace(assessments=env.services),
    )
    assert (await other.get("/v1/me/academic/control-periods")).status_code == 403
