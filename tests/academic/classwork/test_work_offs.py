"""WO-1, WO-3, WO-4, WO-6: templates, saving work-offs with attendance, notices."""

import datetime as dt
from uuid import UUID, uuid4

from app.modules.academic.domain.classwork.errors import (
    NotLessonTeacherError,
    WorkOffNotAbsentError,
    WorkOffNotFoundError,
    WorkOffTemplateLimitError,
    WorkOffTemplateNotFoundError,
    WorkOffTextRequiredError,
)
from app.modules.academic.domain.classwork.work_off import WorkOff
from app.shared.notifications import NotificationDraft, NotificationType
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson

import pytest


def lesson_notices(env: Env) -> list[NotificationDraft]:
    """The lesson_absence drafts written so far."""
    return [
        n for n in env.outbox.notifications if n.type == NotificationType.LESSON_ABSENCE
    ]


async def work_offs_of(env: Env, lesson_id: UUID) -> dict[UUID, WorkOff]:
    """The lesson's work-offs by student id."""
    async with env.services.update_work_off.uow_factory() as uow:
        return {w.student_id: w for w in await uow.work_offs.for_lesson(lesson_id)}


# - - - Templates - - -


async def test_templates_are_listed_oldest_first_for_the_owner_only(env: Env) -> None:
    """WO-1: a teacher sees only their own templates."""
    svc = env.services
    first = await svc.create_work_off_template.execute(env.teacher, " Redo ex. 4 ")
    second = await svc.create_work_off_template.execute(env.teacher, "Essay")
    await svc.create_work_off_template.execute(env.other_teacher, "Other")

    mine = await svc.list_work_off_templates.execute(env.world.teacher.id)

    assert [t.id for t in mine] == [first.id, second.id]
    assert mine[0].text == "Redo ex. 4"


async def test_new_default_clears_the_old_default(env: Env) -> None:
    """WO-1: at most one default per teacher."""
    svc = env.services
    a = await svc.create_work_off_template.execute(env.teacher, "A", True)
    b = await svc.create_work_off_template.execute(env.teacher, "B", True)

    mine = {
        t.id: t for t in await svc.list_work_off_templates.execute(env.teacher.user_id)
    }
    assert [mine[a.id].is_default, mine[b.id].is_default] == [False, True]

    await svc.update_work_off_template.execute(env.teacher, a.id, "A2", True)
    mine = {
        t.id: t for t in await svc.list_work_off_templates.execute(env.teacher.user_id)
    }
    assert [mine[a.id].is_default, mine[b.id].is_default] == [True, False]
    assert mine[a.id].text == "A2"


async def test_twenty_first_template_is_refused(env: Env) -> None:
    """WO-1: the limit is 20 per teacher."""
    for i in range(20):
        await env.services.create_work_off_template.execute(env.teacher, f"T{i}")

    with pytest.raises(WorkOffTemplateLimitError):
        await env.services.create_work_off_template.execute(env.teacher, "one more")


async def test_foreign_template_cannot_be_changed_or_deleted(env: Env) -> None:
    """WO-1: someone else's id is a 404."""
    svc = env.services
    foreign = await svc.create_work_off_template.execute(env.other_teacher, "Theirs")

    with pytest.raises(WorkOffTemplateNotFoundError):
        await svc.update_work_off_template.execute(
            env.teacher, foreign.id, "Mine", False
        )
    with pytest.raises(WorkOffTemplateNotFoundError):
        await svc.delete_work_off_template.execute(env.teacher, foreign.id)
    with pytest.raises(WorkOffTemplateNotFoundError):
        await svc.delete_work_off_template.execute(env.teacher, uuid4())

    assert (
        len(await svc.list_work_off_templates.execute(env.other_teacher.user_id)) == 1
    )


async def test_deleting_a_template_keeps_the_given_work_off_text(env: Env) -> None:
    """WO-1, WO-3: template_id goes to NULL, the text stays."""
    w, svc = env.world, env.services
    lesson_id = await add_lesson(env.maker, w)
    tpl = await svc.create_work_off_template.execute(env.teacher, "Redo")
    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
        work_offs=[{"student_id": w.aziz.id, "template_id": tpl.id}],
    )

    await svc.delete_work_off_template.execute(env.teacher, tpl.id)

    saved = (await work_offs_of(env, lesson_id))[w.aziz.id]
    assert saved.template_id is None
    assert saved.text == "Redo"


# - - - Submit attendance - - -


async def test_per_student_work_off_is_saved_with_text_and_due_date(env: Env) -> None:
    """WO-3, WO-4: template text, blank line, extra text; the student is told."""
    w, svc = env.world, env.services
    lesson_id = await add_lesson(env.maker, w)
    tpl = await svc.create_work_off_template.execute(env.teacher, "Redo ex. 4")

    sheet = await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id, w.bobur.id],
        base_version=0,
        source="staff",
        work_offs=[
            {
                "student_id": str(w.aziz.id),
                "template_id": str(tpl.id),
                "text": "and p. 5",
                "due_date": "2026-10-09",
            }
        ],
    )

    saved = await work_offs_of(env, lesson_id)
    assert set(saved) == {w.aziz.id}
    assert saved[w.aziz.id].text == "Redo ex. 4\n\nand p. 5"
    assert saved[w.aziz.id].due_date == dt.date(2026, 10, 9)
    assert saved[w.aziz.id].assigned_by == w.teacher.id
    assert [item["student_id"] for item in sheet["work_offs"]] == [str(w.aziz.id)]
    notices = {n.user_id: n for n in lesson_notices(env)}
    assert set(notices) == {w.aziz.id, w.bobur.id}
    payload = notices[w.aziz.id].payload
    assert payload == {
        "lesson_id": str(lesson_id),
        "date": DAY.isoformat(),
        "period": 1,
        "subject_name": "Physics",
        "teacher_name": "Gulnara Kalandarova",
        "work_off_text": "Redo ex. 4\n\nand p. 5",
        "due_date": "2026-10-09",
        "update": False,
    }
    assert notices[w.bobur.id].payload["work_off_text"] is None
    assert notices[w.aziz.id].dedupe_key == (
        f"lesson_absence:{lesson_id}:{w.aziz.id}:1"
    )


async def test_old_clients_change_nothing_but_drop_work_offs_of_present_students(
    env: Env,
) -> None:
    """WO-3: no work-off fields keeps tasks of absent students, drops the others."""
    w, svc = env.world, env.services
    lesson_id = await add_lesson(env.maker, w)
    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id, w.bobur.id],
        base_version=0,
        source="staff",
        work_off_mode="common",
        common_work_off={"text": "Read ch. 2"},
    )

    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=1,
        source="staff",
    )

    assert set(await work_offs_of(env, lesson_id)) == {w.aziz.id}


async def test_none_mode_keeps_existing_work_offs_and_adds_nothing(env: Env) -> None:
    """WO-3: "none" attaches nothing new."""
    w, svc = env.world, env.services
    lesson_id = await add_lesson(env.maker, w)
    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
        work_off_mode="common",
        common_work_off={"text": "Read"},
    )

    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id, w.bobur.id],
        base_version=1,
        source="staff",
        work_off_mode="none",
    )

    assert set(await work_offs_of(env, lesson_id)) == {w.aziz.id}


async def test_common_mode_overrides_and_notifies_changed_text(env: Env) -> None:
    """WO-3, WO-4: every absent student gets the task; edited ones get an update."""
    w, svc = env.world, env.services
    lesson_id = await add_lesson(env.maker, w)
    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
        work_offs=[{"student_id": w.aziz.id, "text": "Old"}],
    )
    env.outbox.notifications.clear()

    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id, w.bobur.id],
        base_version=1,
        source="staff",
        work_off_mode="common",
        common_work_off={"text": "New"},
    )

    saved = await work_offs_of(env, lesson_id)
    assert {s: x.text for s, x in saved.items()} == {
        w.aziz.id: "New",
        w.bobur.id: "New",
    }
    updates = {n.user_id: n.payload["update"] for n in lesson_notices(env)}
    assert updates == {w.aziz.id: True, w.bobur.id: False}


async def test_common_mode_requires_a_text(env: Env) -> None:
    """WO-3: no text, no save."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)

    with pytest.raises(WorkOffTextRequiredError):
        await env.services.submit_attendance.execute(
            lesson_id=lesson_id,
            actor=env.teacher,
            absent=[w.aziz.id],
            base_version=0,
            source="staff",
            work_off_mode="common",
            common_work_off={"template_id": None, "text": None},
        )

    assert not env.outbox.notifications


async def test_work_off_for_a_present_student_rolls_the_save_back(env: Env) -> None:
    """WO-3: refused with 422 and the attendance stays unsaved."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)

    with pytest.raises(WorkOffNotAbsentError):
        await env.services.submit_attendance.execute(
            lesson_id=lesson_id,
            actor=env.teacher,
            absent=[w.aziz.id],
            base_version=0,
            source="staff",
            work_offs=[{"student_id": w.bobur.id, "text": "x"}],
        )

    sheet = await env.services.get_attendance_sheet.execute(lesson_id, env.teacher)
    assert sheet["submitted"] is False


async def test_template_of_another_teacher_is_not_found(env: Env) -> None:
    """WO-3: templates must belong to the actor."""
    w, svc = env.world, env.services
    foreign = await svc.create_work_off_template.execute(env.other_teacher, "Theirs")
    lesson_id = await add_lesson(env.maker, w)

    with pytest.raises(WorkOffTemplateNotFoundError):
        await svc.submit_attendance.execute(
            lesson_id=lesson_id,
            actor=env.teacher,
            absent=[w.aziz.id],
            base_version=0,
            source="staff",
            work_offs=[{"student_id": w.aziz.id, "template_id": foreign.id}],
        )


async def test_empty_entry_removes_the_existing_work_off(env: Env) -> None:
    """WO-3: an entry with neither template nor text deletes the task."""
    w, svc = env.world, env.services
    lesson_id = await add_lesson(env.maker, w)
    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
        work_offs=[{"student_id": w.aziz.id, "text": "Redo"}],
    )

    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=1,
        source="staff",
        work_offs=[{"student_id": w.aziz.id}],
    )

    assert await work_offs_of(env, lesson_id) == {}


# - - - Journal toggle - - -


async def test_toggle_notifies_a_newly_absent_student_and_drops_the_work_off(
    env: Env,
) -> None:
    """WO-3, WO-4: marking notifies, un-marking removes the task."""
    w, svc = env.world, env.services
    lesson_id = await add_lesson(env.maker, w)

    version = await svc.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        absent=True,
        base_version=0,
        actor=env.teacher,
    )

    assert [n.user_id for n in lesson_notices(env)] == [w.aziz.id]
    await svc.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=version,
        source="staff",
        work_offs=[{"student_id": w.aziz.id, "text": "Redo"}],
    )
    assert set(await work_offs_of(env, lesson_id)) == {w.aziz.id}

    await svc.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        absent=False,
        base_version=version + 1,
        actor=env.teacher,
    )

    assert await work_offs_of(env, lesson_id) == {}


# - - - Edit, delete, student view - - -


async def give(env: Env, text: str = "Redo") -> tuple[UUID, WorkOff]:
    """Aziz absent with a work-off; returns (lesson id, work-off)."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
        work_offs=[{"student_id": w.aziz.id, "text": text}],
    )
    env.outbox.notifications.clear()
    return lesson_id, (await work_offs_of(env, lesson_id))[w.aziz.id]


async def test_teacher_changes_text_and_the_student_gets_an_update(env: Env) -> None:
    """WO-3, WO-4: a new text queues the update notice."""
    _, work_off = await give(env)

    saved = await env.services.update_work_off.execute(
        work_off.id, env.teacher, text=" Redo ex. 7 ", due_date=dt.date(2026, 10, 12)
    )

    assert saved.text == "Redo ex. 7"
    assert saved.due_date == dt.date(2026, 10, 12)
    [notice] = lesson_notices(env)
    assert notice.payload["update"] is True
    assert notice.payload["work_off_text"] == "Redo ex. 7"


async def test_status_done_sets_done_at_and_assigned_clears_it(env: Env) -> None:
    """WO-3: done_at follows the status; no text change means no notice."""
    _, work_off = await give(env)

    done = await env.services.update_work_off.execute(
        work_off.id, env.teacher, status="done"
    )
    again = await env.services.update_work_off.execute(
        work_off.id, env.teacher, status="assigned"
    )

    assert done.done_at == env.clock.now()
    assert again.done_at is None
    assert again.due_date is None
    assert not lesson_notices(env)


async def test_only_lesson_staff_can_change_or_delete_a_work_off(env: Env) -> None:
    """WO-3: another teacher and the student get 403."""
    _, work_off = await give(env)

    for actor in (env.other_teacher, env.student("aziz")):
        with pytest.raises(NotLessonTeacherError):
            await env.services.update_work_off.execute(
                work_off.id, actor, status="done"
            )
        with pytest.raises(NotLessonTeacherError):
            await env.services.delete_work_off.execute(work_off.id, actor)


async def test_admin_deletes_and_unknown_id_is_not_found(env: Env) -> None:
    """WO-3: Administration may delete; an unknown id is 404."""
    lesson_id, work_off = await give(env)

    await env.services.delete_work_off.execute(work_off.id, env.admin)

    assert await work_offs_of(env, lesson_id) == {}
    with pytest.raises(WorkOffNotFoundError):
        await env.services.delete_work_off.execute(work_off.id, env.admin)
    with pytest.raises(WorkOffNotFoundError):
        await env.services.update_work_off.execute(uuid4(), env.admin, status="done")


async def test_student_sees_only_their_own_open_work_offs(env: Env) -> None:
    """WO-6: open|all filter, subject in the student's locale, teacher name."""
    w, svc = env.world, env.services
    lesson_id, work_off = await give(env, "Redo")
    other = await add_lesson(env.maker, w, period=2)
    await svc.submit_attendance.execute(
        lesson_id=other,
        actor=env.teacher,
        absent=[w.aziz.id, w.bobur.id],
        base_version=0,
        source="staff",
        work_off_mode="common",
        common_work_off={"text": "Common"},
    )
    mine = await svc.list_my_work_offs.execute(w.aziz.id, "ru")
    done = next(i for i in mine if i["text"] == "Redo")
    await svc.update_work_off.execute(work_off.id, env.teacher, status="done")

    open_items = await svc.list_my_work_offs.execute(w.aziz.id, "ru")
    all_items = await svc.list_my_work_offs.execute(w.aziz.id, "ru", "all")
    bobur_items = await svc.list_my_work_offs.execute(w.bobur.id, "en")
    camila_items = await svc.list_my_work_offs.execute(w.camila.id, "en")

    assert done["lesson_id"] == str(lesson_id)
    assert [i["text"] for i in open_items] == ["Common"]
    assert [i["text"] for i in all_items] == ["Common", "Redo"]
    assert all_items[0]["period"] == 2
    assert open_items[0]["subject_name"] == "Физика"
    assert open_items[0]["teacher_name"] == "Gulnara Kalandarova"
    assert [i["text"] for i in bobur_items] == ["Common"]
    assert bobur_items[0]["subject_name"] == "Physics"
    assert camila_items == []
    assert set(open_items[0]) == {
        "id", "lesson_id", "date", "period", "subject_name", "teacher_name",
        "text", "status", "due_date", "done_at", "created_at",
    }  # fmt: skip


async def test_contract_queries_and_commands(env: Env) -> None:
    """WO-5, WO-7: bot contracts return plain dicts."""
    w, svc = env.world, env.services
    tpl = await svc.create_work_off_template.execute(env.teacher, "Redo", True)
    lesson_id, work_off = await give(env)

    templates = await svc.queries.work_off_templates(w.teacher.id)
    mine = await svc.queries.my_work_offs(w.aziz.id, "en")
    teacher_items = await svc.queries.teacher_open_work_offs(w.teacher.id, "en")
    flipped = await svc.commands.set_work_off_status(work_off.id, env.teacher, "done")

    assert templates == [{"id": str(tpl.id), "text": "Redo", "is_default": True}]
    assert [m["id"] for m in mine] == [str(work_off.id)]
    assert teacher_items == [
        {
            "id": str(work_off.id),
            "student_name": "Aziz Abdullaev",
            "group_name": "2TN2",
            "lesson_id": str(lesson_id),
            "date": DAY.isoformat(),
            "subject_name": "Physics",
            "text": "Redo",
        }
    ]
    assert flipped["status"] == "done"
    assert await svc.queries.teacher_open_work_offs(w.teacher.id, "en") == []
