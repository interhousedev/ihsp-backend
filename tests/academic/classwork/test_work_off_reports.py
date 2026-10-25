"""WO-4, WO-6, WO-7, WO-8: curator digest, teacher list, admin list and statistics."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.domain.classwork.errors import NotLessonTeacherError
from app.shared.base_error import ForbiddenError
from app.shared.notifications import NotificationType
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, period_times

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError


async def take(env: Env, lesson_id: UUID, absent: list[UUID], text: str) -> None:
    """Teacher saves attendance with one common work-off."""
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=absent,
        base_version=0,
        source="staff",
        work_off_mode="common",
        common_work_off={"text": text},
    )


async def seed(env: Env) -> dict[str, UUID]:
    """Today physics (Aziz, Bobur absent), yesterday physics (Bobur absent)."""
    w = env.world
    today = await add_lesson(env.maker, w, day=DAY, period=1)
    yesterday = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=1))
    await take(env, today, [w.bobur.id, w.aziz.id], "Redo today")
    await take(env, yesterday, [w.bobur.id], "Redo yesterday")
    env.outbox.notifications.clear()
    return {"today": today, "yesterday": yesterday}


# - - - Sheet - - -


async def test_sheet_lists_the_lessons_work_offs(env: Env) -> None:
    """WO-3: the attendance sheet carries ``work_offs``."""
    ids = await seed(env)

    sheet = await env.services.get_attendance_sheet.execute(ids["today"], env.teacher)

    assert {i["student_id"] for i in sheet["work_offs"]} == {
        str(env.world.aziz.id),
        str(env.world.bobur.id),
    }
    assert sheet["work_offs"][0]["status"] == "assigned"
    assert sheet["work_offs"][0]["assigned_by"] == str(env.world.teacher.id)


# - - - Curator digest - - -


async def test_digest_queues_one_notice_per_group_sorted_by_student(env: Env) -> None:
    """WO-4: the curator gets today's absences with work-off text."""
    w = env.world
    await seed(env)

    result = await env.services.send_absence_digests.execute()

    assert result == {"queued": 1}
    [draft] = env.outbox.notifications
    assert draft.type == NotificationType.CURATOR_ABSENCES
    assert draft.user_id == w.curator.id
    assert draft.dedupe_key == f"curator_absences:{w.curator.id}:{w.group_id}:{DAY}"
    assert draft.payload["group_name"] == "2TN2"
    assert draft.payload["date"] == DAY.isoformat()
    assert [
        (i["student_name"], i["work_off_text"], i["excused"])
        for i in draft.payload["items"]
    ] == [
        ("Aziz Abdullaev", "Redo today", False),
        ("Bobur Karimov", "Redo today", False),
    ]
    assert draft.payload["items"][0]["teacher_name"] == "Gulnara Kalandarova"


async def test_digest_waits_until_30_minutes_after_the_last_lesson(env: Env) -> None:
    """WO-4: a later lesson of the day holds the digest back."""
    await seed(env)
    start, _ = period_times(DAY, 7)
    await add_lesson(env.maker, env.world, day=DAY, period=7)

    assert await env.services.send_absence_digests.execute() == {"waiting": 1}
    assert not env.outbox.notifications

    env.clock.set(start + dt.timedelta(minutes=45 + 31))

    assert await env.services.send_absence_digests.execute() == {"queued": 1}


async def test_digest_skips_weekends_and_days_without_lessons(env: Env) -> None:
    """WO-4: only school days with lessons."""
    assert await env.services.send_absence_digests.execute() == {"skipped": 1}
    await seed(env)
    env.clock.set(dt.datetime(2026, 10, 10, 9, tzinfo=dt.UTC))  # Saturday

    assert await env.services.send_absence_digests.execute() == {"skipped": 1}


async def test_digest_ignores_lessons_without_attendance(env: Env) -> None:
    """WO-4: untaken lessons do not appear."""
    await add_lesson(env.maker, env.world)

    assert await env.services.send_absence_digests.execute() == {"queued": 0}


# - - - Teacher quick list - - -


async def test_teacher_sees_open_work_offs_of_their_lessons(env: Env) -> None:
    """WO-7: only open ones, only the teacher's own."""
    ids = await seed(env)
    [first, *_] = await env.services.list_teacher_work_offs.execute(
        env.world.teacher.id, "en"
    )
    await env.services.update_work_off.execute(
        UUID(first["id"]), env.teacher, status="done"
    )

    mine = await env.services.list_teacher_work_offs.execute(env.world.teacher.id, "en")
    theirs = await env.services.list_teacher_work_offs.execute(
        env.world.other_teacher.id, "en"
    )

    assert len(mine) == 2
    assert {m["lesson_id"] for m in mine} <= {str(v) for v in ids.values()}
    assert theirs == []


# - - - Admin list and statistics - - -


async def test_admin_stats_group_by_each_key_sorted_by_open_count(env: Env) -> None:
    """WO-8: counts per subject, teacher, group and student."""
    w = env.world
    await seed(env)
    [bobur_yesterday] = [
        i
        for i in await env.services.list_my_work_offs.execute(w.bobur.id, "en")
        if i["text"] == "Redo yesterday"
    ]
    await env.services.update_work_off.execute(
        UUID(bobur_yesterday["id"]), env.teacher, status="done"
    )

    by_student = await env.services.work_off_stats.execute(
        env.admin, group_by="student"
    )
    by_subject = await env.services.work_off_stats.execute(
        env.admin, group_by="subject"
    )
    by_group = await env.services.work_off_stats.execute(env.admin, group_by="group")
    by_teacher = await env.services.work_off_stats.execute(
        env.admin, group_by="teacher"
    )

    assert by_student["total_open"] == 2
    assert by_student["from"] == (DAY - dt.timedelta(days=30)).isoformat()
    assert by_student["to"] == DAY.isoformat()
    assert [
        (r["name"], r["open_count"], r["done_count"]) for r in by_student["rows"]
    ] == [
        ("Aziz Abdullaev", 1, 0),
        ("Bobur Karimov", 1, 1),
    ]
    assert by_subject["rows"] == [
        {"key": str(w.physics_id), "name": "Fizika", "open_count": 2, "done_count": 1}
    ]
    assert [r["name"] for r in by_group["rows"]] == ["2TN2"]
    assert [r["name"] for r in by_teacher["rows"]] == ["Gulnara Kalandarova"]


async def test_admin_stats_respect_the_date_range(env: Env) -> None:
    """WO-8: lessons outside [from, to] are not counted."""
    await seed(env)

    stats = await env.services.work_off_stats.execute(
        env.admin, group_by="group", start=DAY, end=DAY
    )

    assert stats["total_open"] == 2


async def test_admin_list_filters_pages_and_counts(env: Env) -> None:
    """WO-8: filters by student/status/date, newest lesson first, with a total."""
    w = env.world
    await seed(env)

    everything = await env.services.list_admin_work_offs.execute(env.admin)
    page = await env.services.list_admin_work_offs.execute(env.admin, limit=1, offset=1)
    bobur = await env.services.list_admin_work_offs.execute(
        env.admin, student_id=w.bobur.id, status="open"
    )
    none_done = await env.services.list_admin_work_offs.execute(
        env.admin, status="done"
    )
    on_day = await env.services.list_admin_work_offs.execute(
        env.admin, start=DAY, end=DAY, group_id=w.group_id, subject_id=w.physics_id,
        teacher_id=w.teacher.id,
    )  # fmt: skip

    assert everything["total"] == 3
    assert [i["date"] for i in everything["items"]][0] == DAY.isoformat()
    assert len(page["items"]) == 1
    assert page["total"] == 3
    assert bobur["total"] == 2
    assert none_done == {"total": 0, "items": []}
    assert on_day["total"] == 2
    item = everything["items"][0]
    assert set(item) == {
        "id", "lesson_id", "date", "period", "subject_name", "teacher_name",
        "group_name", "student_id", "student_name", "text", "status", "due_date",
        "done_at", "created_at",
    }  # fmt: skip
    assert item["teacher_name"] == "Gulnara Kalandarova"
    assert item["group_name"] == "2TN2"


async def test_admin_views_are_forbidden_for_everyone_else(env: Env) -> None:
    """WO-8: teachers, curators and students get 403."""
    for actor in (env.teacher, env.curator, env.student("aziz")):
        with pytest.raises(ForbiddenError):
            await env.services.work_off_stats.execute(actor, group_by="group")
        with pytest.raises(ForbiddenError):
            await env.services.list_admin_work_offs.execute(actor)


# - - - Storage rules - - -


async def test_lesson_delete_cascades_and_duplicates_are_refused(env: Env) -> None:
    """WO-3: unique (lesson, student); work-offs vanish with their lesson."""
    from app.modules.academic.infrastructure.orm.lesson import Lesson
    from app.modules.academic.infrastructure.orm.work_off import WorkOff

    ids = await seed(env)
    async with env.maker() as session:
        existing: Any = (
            (
                await session.execute(
                    sa.select(WorkOff).where(WorkOff.lesson_id == ids["today"])
                )
            )
            .scalars()
            .first()
        )
        session.add(
            WorkOff(
                lesson_id=existing.lesson_id,
                student_id=existing.student_id,
                assigned_by=existing.assigned_by,
                text="dup",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
    async with env.maker() as session:
        await session.execute(sa.delete(Lesson).where(Lesson.id == ids["today"]))
        left = (
            await session.execute(sa.select(sa.func.count()).select_from(WorkOff))
        ).scalar_one()

    assert left == 1


async def test_nobody_but_lesson_staff_can_use_foreign_lessons(env: Env) -> None:
    """WO-3: a teacher of another lesson cannot save work-offs there."""
    lesson_id = await add_lesson(env.maker, env.world)

    with pytest.raises(NotLessonTeacherError):
        await env.services.submit_attendance.execute(
            lesson_id=lesson_id,
            actor=env.other_teacher,
            absent=[env.world.aziz.id],
            base_version=0,
            source="staff",
            work_off_mode="common",
            common_work_off={"text": "x"},
        )
