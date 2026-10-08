"""Changing single lessons and adding extra ones (ADM-10, UF-ADM-07, ACA-7)."""

import datetime as dt

from app.modules.academic.application.schedule.create_extra_lesson import (
    ExtraLessonInput,
)
from app.modules.academic.application.schedule.ports.reader import LessonFilters
from app.modules.academic.application.schedule.update_lesson import LessonPatch
from app.modules.academic.domain.schedule.errors import (
    EntryInvalidError,
    LessonNotFoundError,
    NoBellError,
    NoTermForDateError,
    SubjectNotFoundError,
)
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.room import Room
from app.modules.academic.domain.schedule.subject import Subject
from app.modules.academic.domain.schedule.term import Term
from app.shared.actor import Role
from app.shared.base_error import ConflictError
from app.shared.contracts.identity import UserRef
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.academic.schedule.env import Env
from tests.factories import make_actor

import pytest

ADMIN = make_actor(Role.ADMIN)
WEDNESDAY = dt.date(2026, 10, 14)
Seeded = tuple[Term, Subject, Group, UserRef, Room, UserRef, Lesson]


async def test_an_extra_lesson_gets_its_times_from_the_bells(env: Env) -> None:
    """UF-ADM-07: an extra lesson on a date and period."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group("2TN2")
    teacher = env.teacher()

    item = await env.services.create_extra_lesson.execute(
        ADMIN,
        ExtraLessonInput(
            date=WEDNESDAY,
            period=2,
            subject_id=subject.id,
            teacher_id=teacher.id,
            room_name="Lab",
            audience=[(group.id, None)],
            topic="Revision",
        ),
    )

    assert item["date"] == "2026-10-14" and item["period"] == 2
    assert item["starts_at"].startswith("2026-10-14T04:25")
    assert item["ends_at"].startswith("2026-10-14T05:10")
    assert item["status"] == "scheduled" and item["is_overridden"] is True
    assert item["topic"] == "Revision"
    assert item["room"]["slug"] == "lab"
    assert item["teacher"]["last_name"] == "Kalandarova"
    assert [a["group_name"] for a in item["audience"]] == ["2TN2"]
    assert item["subject"]["name"] == "Математика"
    lessons = await env.lessons()
    assert [x.term_id for x in lessons] == [term.id]
    assert lessons[0].timetable_entry_id is None


async def test_an_extra_lesson_notifies_the_audience_and_the_teacher(env: Env) -> None:
    """UF-ADM-07 step 4: 'Lesson changed' goes to affected students and the teacher."""
    await env.term()
    subject = await env.subject()
    group = await env.group("2TN2")
    other = await env.group("2TN1")
    teacher = env.teacher()
    in_group = await env.student(group)
    outsider = await env.student(other)

    item = await env.services.create_extra_lesson.execute(
        ADMIN,
        ExtraLessonInput(
            date=WEDNESDAY,
            period=2,
            subject_id=subject.id,
            teacher_id=teacher.id,
            room_name=None,
            audience=[(group.id, None)],
        ),
    )

    recipients = {n.user_id for n in env.notifications}
    assert recipients == {in_group.id, teacher.id}
    assert outsider.id not in recipients
    sample = env.notifications[0]
    assert sample.type == NotificationType.LESSON_CHANGED
    assert sample.payload["lesson_id"] == item["id"]
    assert sample.payload["date"] == "2026-10-14" and sample.payload["period"] == 2
    assert sample.payload["subject_name"] == "Математика"
    assert sample.dedupe_key.startswith(f"lesson-changed:{item['id']}:")


async def test_a_subgroup_lesson_notifies_that_subgroup_and_students_without_one(
    env: Env,
) -> None:
    """ACA-2: students without a subgroup see both subgroups' lessons."""
    await env.term()
    subject = await env.subject()
    group = await env.group()
    first = await env.student(group, subgroup=1, last_name="One")
    second = await env.student(group, subgroup=2, last_name="Two")
    unset = await env.student(group, last_name="Unset")

    await env.services.create_extra_lesson.execute(
        ADMIN,
        ExtraLessonInput(
            date=WEDNESDAY,
            period=1,
            subject_id=subject.id,
            teacher_id=None,
            room_name=None,
            audience=[(group.id, 1)],
        ),
    )

    assert {n.user_id for n in env.notifications} == {first.id, unset.id}
    assert second.id not in {n.user_id for n in env.notifications}


async def test_an_extra_lesson_cannot_take_a_busy_teacher(env: Env) -> None:
    """ACA-8: conflicts are rejected, listing the clashing lesson."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group("2TN1")
    other = await env.group("2TN2")
    teacher = env.teacher()
    busy = await env.lesson(
        term,
        day=WEDNESDAY,
        period=2,
        subject=subject,
        audience=[str(group.id)],
        teacher=teacher,
        starts_at=dt.datetime(2026, 10, 14, 4, 25, tzinfo=dt.UTC),
    )

    with pytest.raises(ConflictError) as caught:
        await env.services.create_extra_lesson.execute(
            ADMIN,
            ExtraLessonInput(
                date=WEDNESDAY,
                period=2,
                subject_id=subject.id,
                teacher_id=teacher.id,
                room_name=None,
                audience=[(other.id, None)],
            ),
        )

    conflicts = caught.value.params["conflicts"]
    assert [c["kind"] for c in conflicts] == ["teacher"]
    assert conflicts[0]["with_lesson_id"] == str(busy.id)


async def test_an_extra_lesson_cannot_double_book_a_group(env: Env) -> None:
    """ACA-8: the audience is checked in the application."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.lesson(
        term,
        day=WEDNESDAY,
        period=2,
        subject=subject,
        audience=[str(group.id)],
        starts_at=dt.datetime(2026, 10, 14, 4, 25, tzinfo=dt.UTC),
    )

    with pytest.raises(ConflictError) as caught:
        await env.services.create_extra_lesson.execute(
            ADMIN,
            ExtraLessonInput(
                date=WEDNESDAY,
                period=2,
                subject_id=subject.id,
                teacher_id=None,
                room_name=None,
                audience=[(group.id, 2)],
            ),
        )

    assert [c["kind"] for c in caught.value.params["conflicts"]] == ["audience"]


@pytest.mark.parametrize(
    ("day", "period", "error"),
    [
        (dt.date(2027, 3, 3), 1, NoTermForDateError),
        (WEDNESDAY, 9, NoBellError),
        (dt.date(2026, 10, 18), 1, NoBellError),  # Sunday
    ],
)
async def test_an_extra_lesson_needs_a_term_and_a_bell(
    env: Env, day: dt.date, period: int, error: type[Exception]
) -> None:
    """ACA-4: no term or no bell means no times."""
    await env.term()
    subject = await env.subject()
    group = await env.group()

    with pytest.raises(error):
        await env.services.create_extra_lesson.execute(
            ADMIN,
            ExtraLessonInput(
                date=day,
                period=period,
                subject_id=subject.id,
                teacher_id=None,
                room_name=None,
                audience=[(group.id, None)],
            ),
        )


async def test_an_extra_lesson_needs_known_subject_and_audience(env: Env) -> None:
    """UF-ADM-07: references are checked."""
    await env.term()
    group = await env.group()

    with pytest.raises(SubjectNotFoundError):
        await env.services.create_extra_lesson.execute(
            ADMIN,
            ExtraLessonInput(
                date=WEDNESDAY,
                period=1,
                subject_id=new_id(),
                teacher_id=None,
                room_name=None,
                audience=[(group.id, None)],
            ),
        )
    with pytest.raises(EntryInvalidError):
        await env.services.create_extra_lesson.execute(
            ADMIN,
            ExtraLessonInput(
                date=WEDNESDAY,
                period=1,
                subject_id=new_id(),
                teacher_id=None,
                room_name=None,
                audience=[],
            ),
        )


async def _seed_lesson(env: Env) -> Seeded:
    term = await env.term()
    subject = await env.subject()
    group = await env.group("2TN2")
    teacher = env.teacher()
    room = await env.room("102")
    student = await env.student(group)
    lesson = await env.lesson(
        term,
        day=WEDNESDAY,
        period=2,
        subject=subject,
        audience=[str(group.id)],
        teacher=teacher,
        room=room,
    )
    return term, subject, group, teacher, room, student, lesson


async def test_cancelling_a_lesson_marks_it_changed_and_notifies(env: Env) -> None:
    """UF-ADM-07: cancel; the lesson is changed by hand; people are told."""
    _, _, _, teacher, room, student, lesson = await _seed_lesson(env)

    item = await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(status="cancelled")
    )

    assert item["status"] == "cancelled" and item["is_overridden"] is True
    assert item["changes"] == {"status": ["scheduled", "cancelled"]}
    assert {n.user_id for n in env.notifications} == {student.id, teacher.id}
    assert env.notifications[0].payload["changes"] == {
        "status": ["scheduled", "cancelled"]
    }
    assert env.kicker.calls[-1] == (
        "academic.recompute_due_dates",
        {"lesson_ids": [str(lesson.id)]},
    )
    assert env.cache.invalidated == [room.slug]


async def test_changing_the_room_records_old_and_new_names(env: Env) -> None:
    """README -> Lesson.changes: {"room": ["204", "310"]} for 'Room 204 -> 310'."""
    _, _, _, _, _, _, lesson = await _seed_lesson(env)

    item = await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(room_name="310")
    )

    assert item["changes"] == {"room": ["102", "310"]}
    assert item["room"]["name"] == "310"


async def test_changing_a_field_back_removes_it_from_the_changes(env: Env) -> None:
    """README -> Lesson.changes: only the difference from the timetable is kept."""
    _, _, _, _, _, _, lesson = await _seed_lesson(env)
    await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(room_name="310")
    )
    await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(status="cancelled")
    )

    item = await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(room_name="102")
    )

    assert item["changes"] == {"status": ["scheduled", "cancelled"]}


async def test_changing_the_teacher_notifies_both_teachers(env: Env) -> None:
    """UF-ADM-07: the previous and the new teacher both hear about it."""
    _, _, _, teacher, _, student, lesson = await _seed_lesson(env)
    replacement = env.teacher("Dilorom", "Ismoilova")

    item = await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(teacher_id=replacement.id)
    )

    assert item["changes"]["teacher"] == ["Kalandarova Gulnora", "Ismoilova Dilorom"]
    assert {n.user_id for n in env.notifications} == {
        student.id,
        teacher.id,
        replacement.id,
    }


async def test_clearing_the_teacher_makes_the_lesson_teacher_needed(env: Env) -> None:
    """ACA-7: no teacher means 'teacher needed'."""
    _, _, _, _, _, _, lesson = await _seed_lesson(env)

    item = await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(teacher_id=None)
    )

    assert item["teacher"] is None
    assert item["changes"]["teacher"] == ["Kalandarova Gulnora", None]


async def test_moving_a_lesson_changes_its_date_and_times(env: Env) -> None:
    """UF-ADM-07: move to another date and period."""
    _, _, _, _, _, _, lesson = await _seed_lesson(env)

    item = await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(date=dt.date(2026, 10, 15), period=3)
    )

    assert item["date"] == "2026-10-15" and item["period"] == 3
    assert item["changes"]["date"] == ["2026-10-14", "2026-10-15"]
    assert item["changes"]["time"][1] == "10:20-11:05"
    assert item["starts_at"].startswith("2026-10-15T05:20")


async def test_moving_onto_a_busy_slot_is_rejected(env: Env) -> None:
    """ACA-8: the same teacher cannot be in two lessons."""
    term, subject, group, teacher, _, _, lesson = await _seed_lesson(env)
    other = await env.group("2TN1")
    await env.lesson(
        term,
        day=dt.date(2026, 10, 15),
        period=3,
        subject=subject,
        audience=[str(other.id)],
        teacher=teacher,
        starts_at=dt.datetime(2026, 10, 15, 5, 20, tzinfo=dt.UTC),
    )

    with pytest.raises(ConflictError):
        await env.services.update_lesson.execute(
            ADMIN, lesson.id, LessonPatch(date=dt.date(2026, 10, 15), period=3)
        )

    unchanged = {x.id: x for x in await env.lessons()}[lesson.id]
    assert unchanged.date == WEDNESDAY and unchanged.is_overridden is False
    assert env.notifications == []


async def test_a_topic_alone_is_not_a_hand_change(env: Env) -> None:
    """ACA-21: setting the topic does not freeze the lesson or notify anyone."""
    _, _, _, _, _, _, lesson = await _seed_lesson(env)

    item = await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(topic="Derivatives")
    )

    assert item["topic"] == "Derivatives"
    assert item["is_overridden"] is False and item["changes"] is None
    assert env.notifications == [] and env.kicker.calls == []


async def test_a_lesson_can_change_subject(env: Env) -> None:
    """UF-ADM-07: change the subject."""
    _, _, _, _, _, _, lesson = await _seed_lesson(env)
    physics = await env.subject("Физика", short="Физ")

    item = await env.services.update_lesson.execute(
        ADMIN, lesson.id, LessonPatch(subject_id=physics.id)
    )

    assert item["subject"]["name"] == "Физика"
    assert item["changes"]["subject"] == ["Математика", "Физика"]


async def test_updating_with_a_bad_reference_or_status_is_rejected(env: Env) -> None:
    """UF-ADM-07: unknown lessons, subjects and statuses fail."""
    _, _, _, _, _, _, lesson = await _seed_lesson(env)

    with pytest.raises(LessonNotFoundError):
        await env.services.update_lesson.execute(
            ADMIN, new_id(), LessonPatch(topic="x")
        )
    with pytest.raises(SubjectNotFoundError):
        await env.services.update_lesson.execute(
            ADMIN, lesson.id, LessonPatch(subject_id=new_id())
        )
    with pytest.raises(EntryInvalidError):
        await env.services.update_lesson.execute(
            ADMIN, lesson.id, LessonPatch(status="bogus")
        )


async def test_lessons_are_listed_with_filters_and_a_cursor(env: Env) -> None:
    """ADM-10: search lessons by group, teacher, status; page by date, period, id."""
    term = await env.term()
    subject = await env.subject()
    first = await env.group("2TN1")
    second = await env.group("2TN2")
    teacher = env.teacher()
    for day in (14, 15, 16):
        await env.lesson(
            term,
            day=dt.date(2026, 10, day),
            period=1,
            subject=subject,
            audience=[str(first.id)],
            teacher=teacher,
        )
    await env.lesson(
        term,
        day=dt.date(2026, 10, 14),
        period=2,
        subject=subject,
        audience=[str(second.id)],
    )

    page = await env.services.list_lessons.execute(ADMIN, LessonFilters(), limit=3)
    rest = await env.services.list_lessons.execute(
        ADMIN, LessonFilters(), limit=3, cursor=page.next_cursor
    )
    by_group = await env.services.list_lessons.execute(
        ADMIN, LessonFilters(group_id=second.id)
    )
    needed = await env.services.list_lessons.execute(
        ADMIN, LessonFilters(teacher_needed=True)
    )
    by_teacher = await env.services.list_lessons.execute(
        ADMIN, LessonFilters(teacher_id=teacher.id)
    )
    window = await env.services.list_lessons.execute(
        ADMIN, LessonFilters(start=dt.date(2026, 10, 15), end=dt.date(2026, 10, 15))
    )

    assert [(i["date"], i["period"]) for i in page.items] == [
        ("2026-10-14", 1),
        ("2026-10-14", 2),
        ("2026-10-15", 1),
    ]
    assert page.next_cursor is not None
    assert [(i["date"], i["period"]) for i in rest.items] == [("2026-10-16", 1)]
    assert rest.next_cursor is None
    assert [i["period"] for i in by_group.items] == [2]
    assert (
        len(needed.items) == 1 and len(by_teacher.items) == 3 and len(window.items) == 1
    )


async def test_lessons_can_be_filtered_by_status_and_room(env: Env) -> None:
    """ADM-10: ?status and ?room_id."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    room = await env.room("102")
    live = await env.lesson(
        term,
        day=WEDNESDAY,
        period=1,
        subject=subject,
        audience=[str(group.id)],
        room=room,
    )
    gone = await env.lesson(
        term, day=WEDNESDAY, period=2, subject=subject, audience=[str(group.id)]
    )
    await env.services.update_lesson.execute(
        ADMIN, gone.id, LessonPatch(status="cancelled")
    )

    cancelled = await env.services.list_lessons.execute(
        ADMIN, LessonFilters(status="cancelled")
    )
    in_room = await env.services.list_lessons.execute(
        ADMIN, LessonFilters(room_id=room.id)
    )

    assert [i["id"] for i in cancelled.items] == [str(gone.id)]
    assert [i["id"] for i in in_room.items] == [str(live.id)]
