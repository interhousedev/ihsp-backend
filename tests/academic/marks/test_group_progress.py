"""Group marks and attendance for curators and head students; low exam alerts."""

from uuid import UUID

from app.modules.academic.domain.classwork.errors import NotCuratorError
from app.modules.academic.domain.marks.errors import NotHeadStudentError
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.academic.marks.conftest import Env
from tests.academic.marks.fakes.emis import make_ratings
from tests.academic.marks.fakes.identity import make_user
from tests.academic.marks.world import DAY, MATH_EMIS, PHYSICS_EMIS

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

CURATOR = UUID(int=501)
OTHER_TEACHER = UUID(int=502)


def _actor(user_id: UUID, *roles: Role) -> Actor:
    return Actor(user_id=user_id, roles=frozenset(roles))


async def _set_roles(
    maker: async_sessionmaker[AsyncSession],
    group_id: UUID,
    curator: UUID | None,
    head: UUID | None,
) -> None:
    async with maker() as session:
        group = await session.get(Group, group_id)
        assert group is not None
        group.curator_id, group.head_student_id = curator, head
        await session.commit()


async def _other_group(maker: async_sessionmaker[AsyncSession]) -> UUID:
    group = Group(
        id=new_id(),
        name="1TN1",
        slug="1tn1",
        current_semester=1,
        status="active",
        curator_id=OTHER_TEACHER,
    )
    async with maker() as session:
        session.add(group)
        await session.commit()
    return group.id


async def test_curator_sees_marks_and_attendance_of_the_semester(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """One row per student, one cell per subject, with ПК/ИК and absences."""
    w = env.world
    await _set_roles(sessionmaker_in_tx, w.group_id, CURATOR, w.user_id)
    use_case = services.get_group_progress

    data = await use_case.for_staff(_actor(CURATOR, Role.TEACHER), w.group_id, None)

    assert (data["semester"], data["semesters"]) == (3, [3])
    assert [s["id"] for s in data["subjects"]] == [
        w.math_id,
        w.physics_id,
    ]  # ru: Математика, Физика
    (row,) = data["students"]
    assert row["student"]["id"] == w.user_id
    assert (row["absences"], row["lessons"], row["absence_rate"]) == (1, 1, 1.0)
    math, physics = row["cells"]
    assert (math["semester_mark"], math["midterm_avg"], math["final_avg"]) == (
        4.5,
        5.0,
        None,
    )
    assert (math["absences"], math["lessons"]) == (1, 1)
    assert (physics["semester_mark"], physics["lessons"]) == (3.0, 0)

    empty = await use_case.for_staff(_actor(CURATOR, Role.TEACHER), w.group_id, 2)
    assert empty["semester"] == 2
    assert empty["students"][0]["cells"] == []
    assert empty["students"][0]["gpa"] is None


async def test_head_student_sees_their_own_group(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """The head student gets the same table; another student gets 403."""
    w = env.world
    use_case = services.get_group_progress
    with pytest.raises(NotHeadStudentError):
        await use_case.for_head_student(_actor(w.user_id, Role.STUDENT), None)

    await _set_roles(sessionmaker_in_tx, w.group_id, CURATOR, w.user_id)
    data = await use_case.for_head_student(_actor(w.user_id, Role.STUDENT), 3)
    assert data["group_id"] == w.group_id
    assert len(data["students"][0]["cells"]) == 2


async def test_only_the_curator_or_an_admin_sees_a_group(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """Another group's curator, a plain teacher and a student are refused."""
    w = env.world
    await _set_roles(sessionmaker_in_tx, w.group_id, CURATOR, w.user_id)
    other = await _other_group(sessionmaker_in_tx)
    use_case = services.get_group_progress

    for actor in (
        _actor(OTHER_TEACHER, Role.TEACHER),
        _actor(w.user_id, Role.STUDENT),
    ):
        with pytest.raises(NotCuratorError):
            await use_case.for_staff(actor, w.group_id, None)
    with pytest.raises(NotCuratorError):
        await use_case.for_staff(_actor(CURATOR, Role.TEACHER), other, None)
    admin = await use_case.for_staff(_actor(UUID(int=9), Role.ADMIN), w.group_id, 3)
    assert len(admin["students"]) == 1


async def test_curator_is_told_once_about_low_exam_marks(
    env: Env, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """ПК or ИК of 2 or 3 alert the curator once; lesson marks and 4 do not."""
    w = env.world
    await _set_roles(sessionmaker_in_tx, w.group_id, CURATOR, None)
    env.identity.add(make_user(CURATOR))
    env.emis.set(
        make_ratings(
            MATH_EMIS,
            3,
            [
                ("lesson", DAY, 2),
                ("midterm", DAY, 4),
                ("midterm", DAY, 3),
                ("final", DAY, 2),
            ],
        )
    )
    env.emis.set(make_ratings(PHYSICS_EMIS, 3, [("lesson", DAY, 3)]))
    await env.sync.execute(w.user_id)

    alerts = [
        d
        for d in env.outbox.notifications
        if d.type == NotificationType.CURATOR_EXAM_MARK
    ]
    assert {d.user_id for d in alerts} == {CURATOR}
    assert sorted((d.payload["type"], d.payload["value"]) for d in alerts) == [
        ("final", 2),
        ("midterm", 3),
    ]
    assert alerts[0].payload["group_name"] == "2TN2"

    env.outbox.notifications.clear()
    env.emis.set(
        make_ratings(
            MATH_EMIS,
            3,
            [
                ("lesson", DAY, 2),
                ("midterm", DAY, 4),
                ("midterm", DAY, 3),
                ("final", DAY, 2),
                ("lesson", DAY, 5),
            ],
        )
    )
    await env.sync.execute(w.user_id)
    assert not [
        d
        for d in env.outbox.notifications
        if d.type == NotificationType.CURATOR_EXAM_MARK
    ]
