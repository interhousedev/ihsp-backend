"""Adapters over the real schedule use cases (on fakes and on PostgreSQL).

The shapes the adapters return are validated by the response models of the
composition endpoints, so a drift in the schedule module shows up here.
"""

import datetime as dt
from dataclasses import dataclass

from app.bootstrap.adapters.composition.schedule_overview import (
    ScheduleOverviewAdapter,
)
from app.bootstrap.adapters.composition.student_views import StudentViewsAdapter
from app.bootstrap.adapters.composition.teacher_views import TeacherViewsAdapter
from app.interfaces.http.v1.composition.ports import DayCounts
from app.interfaces.http.v1.composition.shared_schemas import (
    GroupItemResponse,
    LessonItemResponse,
    StudentProfileResponse,
)
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.term import Term
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef
from tests.academic.schedule.env import TERM_END, TERM_START, Env
from tests.bootstrap.composition.fakes import FakeUseCase
from tests.factories import make_actor

MONDAY = dt.date(2026, 10, 5)


@dataclass(slots=True)
class World:
    """A term, a group with a curator, and a subgroup-1 student."""

    term: Term
    group: Group
    curator: UserRef
    student: UserRef


async def seed(env: Env) -> World:
    """Insert the world."""
    curator = env.teacher("Nodira", "Aliyeva")
    group = await env.group("2TN2", curator=curator, semester=3)
    student = await env.student(group, subgroup=1, first_name="Aliya")
    return World(await env.term(), group, curator, student)


async def test_student_profile_and_timetable_match_the_response_models(
    env: Env,
) -> None:
    """The profile nests the group; lessons validate as `LessonItem`."""
    world = await seed(env)
    subject, teacher = await env.subject(), env.teacher()
    lesson = await env.lesson(
        world.term,
        day=MONDAY,
        period=1,
        subject=subject,
        audience=[str(world.group.id)],
        teacher=teacher,
    )
    views = StudentViewsAdapter(
        env.services.get_student_profile,
        env.services.get_student_timetable,
        FakeUseCase(),  # type: ignore[arg-type]
        FakeUseCase(),  # type: ignore[arg-type]
    )

    profile = await views.profile(world.student.id)
    timetable = await views.timetable(world.student.id, MONDAY, MONDAY)

    parsed = StudentProfileResponse.model_validate(profile)
    assert parsed.group.name == "2TN2" and parsed.subgroup == 1
    assert parsed.curator is not None and parsed.curator.last_name == "Aliyeva"
    assert [item["id"] for item in timetable] == [str(lesson.id)]
    item = LessonItemResponse.model_validate(timetable[0])
    assert item.teacher is not None and item.teacher.id == teacher.id


async def test_teacher_timetable_and_curated_groups_match_the_response_models(
    env: Env,
) -> None:
    """The teacher's lessons and the groups they curate."""
    world = await seed(env)
    subject = await env.subject()
    await env.lesson(
        world.term,
        day=MONDAY,
        period=2,
        subject=subject,
        audience=[str(world.group.id)],
        teacher=world.curator,
    )
    views = TeacherViewsAdapter(
        env.services.get_staff_timetable,
        FakeUseCase(),  # type: ignore[arg-type]
        env.services.list_curated_groups,
    )

    lessons = await views.timetable(world.curator.id, MONDAY, MONDAY)
    groups = await views.curated_groups(world.curator.id)

    assert [LessonItemResponse.model_validate(x).period for x in lessons] == [2]
    parsed = [GroupItemResponse.model_validate(x) for x in groups]
    assert [(g.name, g.students_count) for g in parsed] == [("2TN2", 1)]
    assert parsed[0].curator is not None
    assert parsed[0].curator.id == world.curator.id


async def test_overview_reports_term_lessons_and_groups(env: Env) -> None:
    """Term bounds, the day's counts and the active groups from the real use cases."""
    world = await seed(env)
    subject, teacher = await env.subject(), env.teacher()
    audience = [str(world.group.id)]
    for period, with_teacher in ((1, True), (2, False), (3, True)):
        await env.lesson(
            world.term,
            day=MONDAY,
            period=period,
            subject=subject,
            audience=audience,
            teacher=teacher if with_teacher else None,
        )
    await env.lesson(
        world.term,
        day=MONDAY + dt.timedelta(days=1),
        period=1,
        subject=subject,
        audience=audience,
    )
    overview = ScheduleOverviewAdapter(
        env.services.current_term, env.services.list_lessons, env.services.list_groups
    )

    bounds = await overview.term_bounds(MONDAY)
    counts = await overview.day_counts(make_actor(Role.ADMIN), MONDAY)
    group_ids = await overview.active_group_ids()

    assert bounds == (TERM_START, TERM_END)
    assert counts == DayCounts(lessons=3, cancelled=0, teacher_needed=1)
    assert group_ids == [world.group.id]
