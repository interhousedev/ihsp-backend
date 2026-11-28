"""The sync stores EMIS attendance and the views prefer it over the rosters."""

import dataclasses

from app.modules.academic.infrastructure.orm.emis_attendance import EmisAttendance
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Actor, Role
from app.shared.notifications import NotificationType
from tests.academic.marks.conftest import Env
from tests.academic.marks.fakes.emis import make_ratings
from tests.academic.marks.world import DAY, MATH_EMIS, PHYSICS_EMIS

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _sync_emis_attendance(env: Env) -> None:
    """Math: EMIS total 0 absences; physics: EMIS absent on DAY."""
    math = make_ratings(MATH_EMIS, 3, [("lesson", DAY, 5)], rating=90)
    physics = make_ratings(PHYSICS_EMIS, 3, [("lesson", DAY, 3)])
    env.emis.set(dataclasses.replace(math, absence_total=0))
    env.emis.set(dataclasses.replace(physics, absent_dates=(DAY,)))
    await env.sync.execute(env.world.user_id)


async def test_sync_stores_emis_attendance(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """One row per subject EMIS reported attendance for."""
    await _sync_emis_attendance(env)
    async with sessionmaker_in_tx() as session:
        rows = (await session.scalars(sa.select(EmisAttendance))).all()
    by_subject = {r.subject_id: r for r in rows}
    w = env.world
    assert by_subject[w.math_id].absence_total == 0
    assert by_subject[w.math_id].absent_dates is None
    assert by_subject[w.physics_id].absent_dates == [DAY]
    assert by_subject[w.physics_id].semester == 3


async def test_group_progress_prefers_emis_and_labels_the_source(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """EMIS total overrides the roster absence; an EMIS-only absence is counted."""
    w = env.world
    curator = Actor(user_id=w.teacher_id, roles=frozenset({Role.TEACHER}))
    async with sessionmaker_in_tx() as session:
        group = await session.get(Group, w.group_id)
        assert group is not None
        group.curator_id = w.teacher_id
        await session.commit()

    before = await services.get_group_progress.for_staff(curator, w.group_id, 3)
    assert before["students"][0]["attendance_source"] == "platform"

    await _sync_emis_attendance(env)
    data = await services.get_group_progress.for_staff(curator, w.group_id, 3)
    (row,) = data["students"]
    cells = {c["subject_id"]: c for c in row["cells"]}
    math, physics = cells[w.math_id], cells[w.physics_id]
    assert (math["absences"], math["lessons"], math["attendance_source"]) == (
        0,
        1,
        "mixed",  # absences from EMIS, the lesson count from the roster
    )
    assert (physics["absences"], physics["lessons"]) == (1, 1)
    assert physics["attendance_source"] == "emis"
    assert (row["absences"], row["attendance_source"]) == (1, "mixed")


async def test_subject_detail_marks_the_emis_absence_on_the_lesson(
    services: MarksServices, env: Env
) -> None:
    """The physics lesson on DAY is absent from EMIS though no roster exists."""
    await _sync_emis_attendance(env)
    student = Actor(user_id=env.world.user_id, roles=frozenset({Role.STUDENT}))
    detail = await services.get_subject_detail.execute(student, env.world.physics_id, 3)
    (lesson,) = [x for x in detail["lessons"] if x["id"] == env.world.physics_lesson]
    assert (lesson["attendance"], lesson["attendance_source"]) == ("absent", "emis")
    assert detail["attendance_source"] == "emis"


def _absence_notices(env: Env) -> list[object]:
    return [
        n for n in env.outbox.notifications if n.type == NotificationType.LESSON_ABSENCE
    ]


async def test_new_emis_absence_notifies_the_student_once(env: Env) -> None:
    """A regular sync announces a new EMIS absence; a repeat sync does not."""
    await _sync_emis_attendance(env)
    (notice,) = _absence_notices(env)
    w = env.world
    assert notice.user_id == w.user_id  # type: ignore[attr-defined]
    assert notice.payload["source"] == "emis"  # type: ignore[attr-defined]
    assert notice.dedupe_key == (  # type: ignore[attr-defined]
        f"emis_absence:{w.user_id}:{w.physics_id}:{DAY.isoformat()}"
    )

    await _sync_emis_attendance(env)
    assert len(_absence_notices(env)) == 1


async def test_absence_corrected_to_present_is_not_announced_again(env: Env) -> None:
    """Absent, then present, then nothing new: still one notice."""
    await _sync_emis_attendance(env)
    physics = make_ratings(PHYSICS_EMIS, 3, [("lesson", DAY, 3)])
    env.emis.set(dataclasses.replace(physics, absent_dates=()))
    await env.sync.execute(env.world.user_id)
    assert len(_absence_notices(env)) == 1
