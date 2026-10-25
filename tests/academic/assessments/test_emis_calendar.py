"""EMIS control lessons reach the exam calendar through ScheduleQueries.

The generator reads them with ``ScheduleQueries.emis_control_lessons``. A lesson inside
a control week Administration set becomes a planned midterm or final of its subject on
its date; EMIS topics are not trusted, only the lesson kind is.
"""

import datetime as dt
from typing import Any, cast
from uuid import UUID, uuid4

from app.modules.academic.application.assessments.generate_tentative import (
    GenerateTentativeAssessments,
)
from app.modules.academic.infrastructure.assessments.uow import (
    SqlAssessmentsUnitOfWork,
)
from app.modules.academic.infrastructure.orm.group import Group
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import LessonRef, ScheduleQueries
from tests.academic.assessments.conftest import Env, add_exam_lesson

D = dt.date.fromisoformat

TODAY = D("2026-10-06")  # the fixed clock, in Tashkent
SINCE, UNTIL = TODAY - dt.timedelta(days=14), TODAY + dt.timedelta(days=120)


class SpySchedule:
    """The one ScheduleQueries method the generator uses, with a canned answer."""

    def __init__(self, refs: list[LessonRef]) -> None:
        """Remember what to answer."""
        self.refs = refs
        self.calls: list[tuple[list[UUID], dt.date, dt.date]] = []

    async def emis_control_lessons(
        self, group_ids: list[UUID], start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Record the question and answer it."""
        self.calls.append((list(group_ids), start, end))
        return self.refs


async def _ref(env: Env, **kwargs: Any) -> LessonRef:
    """A scheduled EMIS midterm of math for the whole group on 2026-10-21.

    The lesson row exists (controls link to it); its stored kind is "other", so only
    the answer of the spy makes it a control.
    """
    day = kwargs.pop("date", D("2026-10-21"))
    hour = kwargs.pop("hour", 4)  # a teacher cannot be in two lessons at once
    lesson_id = await add_exam_lesson(
        env, day, kind="other", subject_id=kwargs.get("subject_id"), hour=hour
    )
    start = dt.datetime.combine(day, dt.time(hour, 0), tzinfo=dt.UTC)
    fields: dict[str, Any] = {
        "id": lesson_id,
        "date": day,
        "period": 4,
        "starts_at": start,
        "ends_at": start + dt.timedelta(minutes=45),
        "subject_id": env.world.math_id,
        "subject_name": "Mathematics",
        "teacher_id": env.world.teacher_id,
        "room_id": None,
        "room_slug": None,
        "room_name": "204",
        "audience": (str(env.world.group_id),),
        "group_names": ("2TN2",),
        "status": "scheduled",
        "topic": None,
        "homework_text": None,
        "homework_due_date": None,
        "kind": "midterm",
        "topic_source": None,
    }
    fields.update(kwargs)
    return LessonRef(**fields)


def _generator(env: Env, schedule: SpySchedule) -> GenerateTentativeAssessments:
    def uow_factory() -> SqlAssessmentsUnitOfWork:
        return SqlAssessmentsUnitOfWork(
            env.maker, env.outbox.write_notifications, env.outbox.write_audit, None
        )

    return GenerateTentativeAssessments(
        uow_factory=uow_factory,
        schedule=cast(ScheduleQueries, schedule),
        clock=env.clock,
    )


async def _stored(env: Env) -> list[dict[str, Any]]:
    """Every dated control of the student's calendar (the week cards have no date)."""
    items = await env.services.list_mine.execute(env.student(), until=D("2027-01-31"))
    return [i for i in items if i["has_date"]]


# - - - The generator asks the schedule - - -


async def test_the_generator_asks_the_schedule_for_the_active_groups(env: Env) -> None:
    """Archived groups are not asked about; the window is -14 to +120 days."""
    async with env.maker() as session:
        session.add(
            Group(id=uuid4(), name="OLD1", slug="old1", status="archived"),
        )
        await session.commit()
    spy = SpySchedule([])

    result = await _generator(env, spy).execute()

    assert spy.calls == [([env.world.group_id], SINCE, UNTIL)]
    assert result == {"lessons": 0, "created": 0, "confirmed": 0}


async def test_a_midterm_lesson_inside_a_week_is_a_planned_midterm_on_its_date(
    env: Env,
) -> None:
    """The control of the subject is the lesson's: same subject, date, time and room."""
    ref = await _ref(env, topic="Algebra review", topic_source="manual")
    spy = SpySchedule([ref])

    result = await _generator(env, spy).execute()

    assert result == {"lessons": 1, "created": 1, "confirmed": 0}
    (item,) = await _stored(env)
    assert (item["kind"], item["status"], item["source"]) == (
        "midterm",
        "planned",
        "emis",
    )
    assert (item["date"], item["control"], item["lesson_id"]) == (
        D("2026-10-21"),
        "midterm_1",
        ref.id,
    )
    assert (item["subject"]["id"], item["room"], item["title"]) == (
        env.world.math_id,
        "204",
        "Algebra review",
    )
    assert item["starts_at"] == ref.starts_at


async def test_a_final_lesson_is_planned_only_in_the_final_week(env: Env) -> None:
    """The week of the final, not a midterm week, plans a final."""
    spy = SpySchedule(
        [
            await _ref(env, kind="final", date=D("2026-12-15")),
            await _ref(
                env, kind="final", date=D("2026-11-24"), subject_id=env.world.physics_id
            ),
        ]
    )

    await _generator(env, spy).execute()

    by_subject = {i["subject"]["id"]: i for i in await _stored(env)}
    inside = by_subject[env.world.math_id]
    assert (inside["kind"], inside["status"], inside["control"]) == (
        "final",
        "planned",
        "final",
    )
    assert by_subject[env.world.physics_id]["status"] == "tentative"


async def test_a_lesson_outside_every_week_is_never_planned(env: Env) -> None:
    """Outside the weeks EMIS only hints: tentative, until someone confirms it."""
    spy = SpySchedule([await _ref(env, date=D("2026-11-10"))])

    await _generator(env, spy).execute()

    (item,) = await _stored(env)
    assert (item["status"], item["control"], item["source"]) == (
        "tentative",
        None,
        "emis",
    )


async def test_a_lesson_that_is_not_a_midterm_or_a_final_is_ignored(env: Env) -> None:
    """Only the kind is trusted: a lecture the schedule hands over is dropped."""
    spy = SpySchedule(
        [
            await _ref(env, kind="lecture", hour=5),
            await _ref(env, kind="other", hour=6),
            await _ref(env, kind="midterm", status="cancelled", hour=7),
        ]
    )

    result = await _generator(env, spy).execute()

    assert result == {"lessons": 0, "created": 0, "confirmed": 0}
    assert await _stored(env) == []


async def test_an_emis_topic_is_never_the_title(env: Env) -> None:
    """EMIS topics are wrong: only a topic a person wrote names the control."""
    spy = SpySchedule(
        [
            await _ref(env, topic="From EMIS", topic_source="emis"),
            await _ref(
                env,
                date=D("2026-10-22"),
                subject_id=env.world.physics_id,
                topic="Written by hand",
                topic_source="manual",
            ),
        ]
    )

    await _generator(env, spy).execute()

    titles = {i["subject"]["id"]: i["title"] for i in await _stored(env)}
    assert titles == {env.world.math_id: "", env.world.physics_id: "Written by hand"}


# - - - Through the real schedule queries - - -


async def test_lessons_flow_from_the_schedule_into_the_students_calendar(
    env: Env,
) -> None:
    """Real wiring: scheduled midterms and finals; a lecture and a cancelled one."""
    await add_exam_lesson(env, D("2026-10-21"))
    await add_exam_lesson(
        env, D("2026-12-15"), kind="final", subject_id=env.world.physics_id
    )
    await add_exam_lesson(env, D("2026-10-22"), kind="lecture")
    await add_exam_lesson(env, D("2026-10-23"), status="cancelled")

    result = await env.services.generate_suggestions.execute()

    assert result == {"lessons": 2, "created": 2, "confirmed": 0}
    math, physics = await _stored(env)
    assert (math["subject"]["id"], math["kind"], math["date"], math["status"]) == (
        env.world.math_id,
        "midterm",
        D("2026-10-21"),
        "planned",
    )
    assert (
        physics["subject"]["id"],
        physics["kind"],
        physics["date"],
        physics["status"],
    ) == (env.world.physics_id, "final", D("2026-12-15"), "planned")


async def test_a_subgroup_lesson_reaches_the_subgroup_and_the_unset_students(
    env: Env,
) -> None:
    """The schedule matches subgroup audiences: subgroup 2 is not seen by subgroup 1."""
    await add_exam_lesson(env, D("2026-10-21"), audience=[f"{env.world.group_id}:2"])
    await env.services.generate_suggestions.execute()
    first = Actor(env.subgroup_id, frozenset({Role.STUDENT}))

    unset = await env.services.list_mine.execute(env.student(), until=D("2026-11-01"))
    sub_one = await env.services.list_mine.execute(first, until=D("2026-11-01"))

    assert [i["date"] for i in unset if i["has_date"]] == [D("2026-10-21")]
    assert [i for i in sub_one if i["has_date"]] == []


async def test_an_emis_topic_on_the_lesson_does_not_name_the_control(env: Env) -> None:
    """A lesson kept from before topics were dropped still has its EMIS topic."""
    await add_exam_lesson(
        env, D("2026-10-21"), topic="From EMIS", emis_topic="From EMIS"
    )
    await add_exam_lesson(
        env,
        D("2026-10-22"),
        topic="Typed by a teacher",
        subject_id=env.world.physics_id,
    )

    await env.services.generate_suggestions.execute()

    titles = {i["subject"]["id"]: i["title"] for i in await _stored(env)}
    assert titles == {
        env.world.math_id: "",
        env.world.physics_id: "Typed by a teacher",
    }
