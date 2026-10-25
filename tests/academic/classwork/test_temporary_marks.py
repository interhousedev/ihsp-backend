"""TMP-1, TMP-3: temporary gradebook use cases, HTTP authz and the reminder job."""

import datetime as dt
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.staff_temporary_marks import ROUTERS
from app.modules.academic.domain.classwork.errors import (
    NotLessonTeacherError,
    StudentNotInLessonError,
    TemporaryMarkNotFoundError,
)
from app.shared.actor import Actor
from app.shared.notifications import NotificationType
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, add_mark, period_times
from tests.conftest import HttpClientFactory

import pytest
from httpx import AsyncClient


async def client_as(
    http_client: HttpClientFactory, env: Env, actor: Actor
) -> AsyncClient:
    """A client whose requests are authenticated as the actor."""
    return await http_client(
        ROUTERS,
        overrides={get_actor: lambda: actor},
        academic=SimpleNamespace(classwork=env.services),
    )


def _url(lesson_id: UUID, student_id: UUID | None = None) -> str:
    base = f"/v1/staff/lessons/{lesson_id}/temporary-marks"
    return base if student_id is None else f"{base}/{student_id}"


# - - - Use cases - - -


async def test_set_list_update_delete(env: Env) -> None:
    """TMP-1: upsert per lesson and student, names in the view, delete."""
    w = env.world
    lesson = await add_lesson(env.maker, w)
    s = env.services

    first = await s.set_temporary_mark.execute(
        lesson, w.aziz.id, env.teacher, value=4, comment=" oral "
    )
    again = await s.set_temporary_mark.execute(lesson, w.aziz.id, env.teacher, value=5)
    listed = await s.list_lesson_temporary_marks.execute(lesson, env.teacher)

    assert first.mark.comment == "oral"
    assert again.mark.id == first.mark.id
    assert [(v.mark.value, v.mark.comment) for v in listed] == [(5, None)]
    item = listed[0].to_json()
    assert item["student_name"] == "Aziz Abdullaev"
    assert item["group_name"] == "2TN2"
    assert item["subject_name"]
    assert item["lesson_date"] == DAY.isoformat()
    assert item["teacher_name"] == "Gulnara Kalandarova"

    await s.delete_temporary_mark.execute(lesson, w.aziz.id, env.teacher)
    assert await s.list_lesson_temporary_marks.execute(lesson, env.teacher) == []
    with pytest.raises(TemporaryMarkNotFoundError):
        await s.delete_temporary_mark.execute(lesson, w.aziz.id, env.teacher)


async def test_only_lesson_teacher_or_admin_and_only_roster_students(
    env: Env,
) -> None:
    """TMP-1: another teacher is refused; the admin may; outsiders are refused."""
    w = env.world
    lesson = await add_lesson(env.maker, w)
    s = env.services

    with pytest.raises(NotLessonTeacherError):
        await s.set_temporary_mark.execute(
            lesson, w.aziz.id, env.other_teacher, value=4
        )
    with pytest.raises(NotLessonTeacherError):
        await s.list_lesson_temporary_marks.execute(lesson, env.other_teacher)
    with pytest.raises(StudentNotInLessonError):
        await s.set_temporary_mark.execute(lesson, w.outsider.id, env.teacher, value=4)
    by_admin = await s.set_temporary_mark.execute(lesson, w.aziz.id, env.admin, value=3)
    assert by_admin.mark.author_id == w.admin.id
    with pytest.raises(NotLessonTeacherError):
        await s.delete_temporary_mark.execute(lesson, w.aziz.id, env.other_teacher)


async def test_pending_hides_marks_already_in_emis(env: Env) -> None:
    """TMP-3: a mark EMIS already has on the date is not pending."""
    w = env.world
    lesson = await add_lesson(env.maker, w)
    s = env.services
    await s.set_temporary_mark.execute(lesson, w.aziz.id, env.teacher, value=4)
    await s.set_temporary_mark.execute(lesson, w.bobur.id, env.teacher, value=3)
    await add_mark(env.maker, w.bobur.id, w.physics_id, value=3, day=DAY)

    mine = await s.list_pending_temporary_marks.execute(env.teacher)
    other = await s.list_pending_temporary_marks.execute(env.other_teacher)
    everyone = await s.list_pending_temporary_marks.execute(env.admin)

    assert [v.mark.student_id for v in mine] == [w.aziz.id]
    assert other == []
    assert [v.mark.student_id for v in everyone] == [w.aziz.id]


# - - - HTTP - - -


async def test_http_routes_and_authz(env: Env, http_client: HttpClientFactory) -> None:
    """TMP-1: routes for the lesson's teacher; others get 403, students too."""
    w = env.world
    lesson = await add_lesson(env.maker, w)
    teacher = await client_as(http_client, env, env.teacher)
    other = await client_as(http_client, env, env.other_teacher)
    student = await client_as(http_client, env, env.student("aziz"))
    admin = await client_as(http_client, env, env.admin)

    put = await teacher.put(_url(lesson, w.aziz.id), json={"value": 5})
    bad = await teacher.put(_url(lesson, w.aziz.id), json={"value": 6})
    foreign = await other.put(_url(lesson, w.aziz.id), json={"value": 2})
    refused = await student.get(_url(lesson))
    listed = await admin.get(_url(lesson))
    pending = await teacher.get("/v1/staff/temporary-marks/pending")
    other_pending = await other.get("/v1/staff/temporary-marks/pending")
    missing = await teacher.get(_url(uuid4()))
    deleted = await teacher.delete(_url(lesson, w.aziz.id))
    gone = await teacher.delete(_url(lesson, w.aziz.id))

    assert put.status_code == 200, put.text
    assert put.json()["value"] == 5
    assert put.json()["student_name"] == "Aziz Abdullaev"
    assert bad.status_code == 422
    assert foreign.status_code == 403
    assert refused.status_code == 403
    assert [i["value"] for i in listed.json()["items"]] == [5]
    assert [i["student_id"] for i in pending.json()["items"]] == [str(w.aziz.id)]
    assert other_pending.json()["items"] == []
    assert missing.status_code == 404
    assert deleted.status_code == 204
    assert gone.status_code == 404


# - - - Reminder job - - -


async def test_reminder_lists_pending_marks_once_per_teacher(env: Env) -> None:
    """TMP-3: after lessons, one notice per teacher with every pending mark."""
    w = env.world
    lesson = await add_lesson(env.maker, w)
    await env.services.set_temporary_mark.execute(
        lesson, w.aziz.id, env.teacher, value=4, comment="test"
    )

    result = await env.services.send_temporary_mark_reminders.execute()

    assert result == {"queued": 1}
    [draft] = env.outbox.notifications
    assert draft.type == NotificationType.TEACHER_TEMPORARY_MARKS
    assert draft.user_id == w.teacher.id
    assert draft.dedupe_key == f"teacher_temporary_marks:{w.teacher.id}:{DAY}"
    assert draft.payload["count"] == 1
    [item] = draft.payload["items"]
    assert (item["student_name"], item["group_name"], item["value"]) == (
        "Aziz Abdullaev",
        "2TN2",
        4,
    )
    assert item["comment"] == "test"
    assert item["subject_name"]
    assert item["period"] == 1


async def test_reminder_waits_skips_and_sends_nothing_without_marks(
    env: Env,
) -> None:
    """TMP-3: Monday to Friday only, after the last lesson, only with marks."""
    w = env.world
    assert await env.services.send_temporary_mark_reminders.execute() == {"skipped": 1}
    await add_lesson(env.maker, w)
    assert await env.services.send_temporary_mark_reminders.execute() == {"queued": 0}
    start, _ = period_times(DAY, 7)
    late = await add_lesson(env.maker, w, period=7)
    await env.services.set_temporary_mark.execute(late, w.aziz.id, env.teacher, value=4)
    assert await env.services.send_temporary_mark_reminders.execute() == {"waiting": 1}
    env.clock.set(start + dt.timedelta(minutes=45 + 31))
    assert await env.services.send_temporary_mark_reminders.execute() == {"queued": 1}
    env.clock.set(dt.datetime(2026, 10, 10, 9, tzinfo=dt.UTC))  # Saturday
    assert await env.services.send_temporary_mark_reminders.execute() == {"skipped": 1}
