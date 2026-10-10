"""ACA-1, ACA-4, ACA-5, ACA-6, ACA-7, ID-10: a group's timetable is read from EMIS."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.schedule.sync_group_timetable import (
    TimetableResult,
)
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.subject import Subject
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.shared.actor import SYSTEM_USER_ID, Role
from app.shared.contracts.emis import EmisAuthFailed, EmisTopic, EmisUnavailable
from app.shared.contracts.identity import UserRef, UserStatus
from tests.academic.schedule.emis_builders import (
    HISTORY,
    PHYSICS,
    YULDASHEV,
    day,
    klass,
    weekly,
)
from tests.academic.schedule.env import TODAY, Env

import pytest


async def run(env: Env, group_id: UUID, user_id: UUID) -> TimetableResult:
    return await env.emis_import.sync_group_timetable.execute(
        group_id=group_id, user_id=user_id
    )


async def entries_of(env: Env, term_id: UUID) -> list[TimetableEntry]:
    async with env.uow_factory() as uow:
        found = await uow.entries.list_for_term(term_id)
    return sorted(found, key=lambda e: (e.weekday, e.period, e.week_parity, e.audience))


async def lessons_of(env: Env) -> list[Lesson]:
    return await env.lessons()


async def set_up(
    env: Env, *, subgroup: int | None = None
) -> tuple[Term, Group, UserRef]:
    """A term, the group 2TN2 and one student of it."""
    term = await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    user = await env.student(group, subgroup=subgroup)
    return term, group, user


# - - - the first import - - -


async def test_a_group_without_a_timetable_gets_entries_teachers_rooms_and_lessons(
    env: Env,
) -> None:
    """ACA-1: weekly entries, EMIS teachers and rooms, lessons from today on."""
    term, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0) + weekly(
        3, 1, subject=PHYSICS, teacher=YULDASHEV, room="204"
    )

    result = await run(env, group.id, user.id)

    assert result.status == "synced"
    assert (result.entries, result.merged, result.skipped) == (2, 0, 0)
    entries = await entries_of(env, term.id)
    assert [(e.weekday, e.period, e.week_parity, e.source) for e in entries] == [
        (2, 1, "every", "emis"),
        (3, 2, "every", "emis"),
    ]
    assert [e.audience for e in entries] == [[str(group.id)]] * 2
    assert result.teachers == 2
    pending = [
        u
        for u in env.identity.users.values()
        if u.status is UserStatus.PENDING_ACTIVATION
    ]
    assert sorted(u.last_name for u in pending) == ["Kalandarova", "Yuldashev"]
    lessons = await lessons_of(env)
    assert [x.date for x in lessons] == [
        day(week, weekday) for week in range(4) for weekday in (2, 3)
    ]
    assert result.lessons == len(lessons) == 8


async def test_lessons_start_and_end_at_the_emis_bell_times(env: Env) -> None:
    """ACA-4: the bells are refreshed first, so the first pair is 08:30-09:50."""
    _, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0)

    await run(env, group.id, user.id)

    first = (await lessons_of(env))[0]
    assert first.starts_at == dt.datetime(2026, 10, 6, 3, 30, tzinfo=dt.UTC)
    assert first.ends_at == dt.datetime(2026, 10, 6, 4, 50, tzinfo=dt.UTC)


async def test_the_bells_can_be_left_to_the_caller(env: Env) -> None:
    """ACA-4: the 20:00 run syncs them once itself."""
    _, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0)

    await env.emis_import.sync_group_timetable.execute(
        group_id=group.id, user_id=user.id, refresh_bells=False
    )

    assert ("class_hours", user.id) not in env.emis.calls


async def test_odd_and_even_slots_become_parity_entries_and_lessons_follow(
    env: Env,
) -> None:
    """ACA-5: Friday pair 1 is History in odd weeks and Physics in even weeks."""
    term, group, user = await set_up(env)
    env.emis.classes = (
        weekly(2, 0)
        + weekly(5, 0, weeks=(1, 3), subject=HISTORY)
        + weekly(5, 0, weeks=(0, 2), subject=PHYSICS)
    )

    await run(env, group.id, user.id)

    entries = await entries_of(env, term.id)
    fridays = [e for e in entries if e.weekday == 5]
    assert sorted(e.week_parity for e in fridays) == ["even", "odd"]
    by_date = {x.date: x for x in await lessons_of(env) if x.date.isoweekday() == 5}
    assert sorted(by_date) == [day(0, 5), day(1, 5), day(2, 5), day(3, 5)]
    names = {x.date: x.subject_id for x in by_date.values()}
    assert names[day(0, 5)] == names[day(2, 5)] != names[day(1, 5)] == names[day(3, 5)]


async def test_classes_on_a_saturday_are_ignored(env: Env) -> None:
    """The lyceum does not study on Saturdays: no entry, no lesson for them."""
    term, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0) + weekly(6, 0, subject=HISTORY)

    await run(env, group.id, user.id)

    entries = await entries_of(env, term.id)
    assert [(e.weekday, e.period) for e in entries] == [(2, 1)]
    assert {x.date.isoweekday() for x in await lessons_of(env)} == {2}


# - - - halves - - -


async def test_the_students_subgroup_is_set_from_the_class_when_unset(env: Env) -> None:
    """ACA-2: EMIS says which half the student is in; the entry is for that half."""
    term, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0, subgroup=2) + weekly(3, 0)

    result = await run(env, group.id, user.id)

    assert result.subgroup == 2
    async with env.uow_factory() as uow:
        student = await uow.students.get(user.id)
    assert student is not None and student.subgroup == 2
    assert student.subgroup_set_by == SYSTEM_USER_ID
    entries = await entries_of(env, term.id)
    assert [e.audience for e in entries] == [[f"{group.id}:2"], [str(group.id)]]
    assert any(a.type == "subgroup.assigned" for a in env.audits)
    subject = await _subject(env, entries[0].subject_id)
    assert subject.can_be_divided


async def test_a_subgroup_a_curator_set_is_not_changed(env: Env) -> None:
    """ACA-3: only an unset subgroup is filled in."""
    _, group, user = await set_up(env, subgroup=1)
    env.emis.classes = weekly(2, 0, subgroup=2)

    result = await run(env, group.id, user.id)

    assert result.subgroup == 1
    async with env.uow_factory() as uow:
        student = await uow.students.get(user.id)
    assert student is not None and student.subgroup == 1


async def test_the_other_half_arrives_with_a_student_of_that_half(env: Env) -> None:
    """ACA-2: each half comes from its own students and never deletes the other's."""
    term = await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    first = await env.student(group, first_name="Aliya")
    second = await env.student(group, first_name="Bobur", last_name="Rahimov")
    env.emis.by_user = {
        first.id: weekly(2, 0, subgroup=1) + weekly(3, 0),
        second.id: weekly(2, 0, subgroup=2, teacher=YULDASHEV, room="204")
        + weekly(3, 0),
    }

    await run(env, group.id, first.id)
    one_half = await entries_of(env, term.id)
    await run(env, group.id, second.id)
    both = await entries_of(env, term.id)
    await run(env, group.id, first.id)
    again = await entries_of(env, term.id)

    assert len(one_half) == 2 and len(both) == 3
    assert sorted(e.audience[0].partition(":")[2] for e in both) == ["", "1", "2"]
    assert [e.id for e in again] == [e.id for e in both]


async def _subject(env: Env, subject_id: UUID) -> Subject:
    async with env.uow_factory() as uow:
        found = await uow.subjects.get(subject_id)
    assert found is not None
    return found


# - - - lesson details - - -


def topic(
    *,
    topic_file_url: str | None = None,
    homework_file_url: str | None = None,
    video_url: str | None = None,
) -> EmisTopic:
    return EmisTopic(
        name="Jadids",
        description="read it",
        topic_file_url=topic_file_url,
        homework_file_url=homework_file_url,
        video_url=video_url,
    )


async def lesson_on(env: Env, when: dt.date, period: int = 1) -> Lesson:
    found = [x for x in await lessons_of(env) if (x.date, x.period) == (when, period)]
    assert len(found) == 1, found
    return found[0]


async def test_kind_and_class_id_are_stored_on_the_lesson(env: Env) -> None:
    """ACA-7: the lesson mirrors the EMIS class: its kind (exam weeks) and its id."""
    _, group, user = await set_up(env)
    env.emis.classes = [
        klass(0, 2, 0, kind="lecture", class_id=111),
        klass(1, 2, 0, kind="midterm", class_id=112),
        klass(2, 2, 0, kind="final", class_id=113),
    ]

    await run(env, group.id, user.id)

    kinds = [await lesson_on(env, day(week, 2)) for week in range(3)]
    assert [(x.kind, x.emis_class_id) for x in kinds] == [
        ("lecture", 111),
        ("midterm", 112),
        ("final", 113),
    ]


async def test_emis_topics_files_and_videos_are_left_out_by_default(env: Env) -> None:
    """EMIS__IMPORT_TOPICS is off: EMIS materials are not trusted, so none arrive."""
    _, group, user = await set_up(env)
    files = topic(
        topic_file_url="https://cdn-emis.edu.uz/files/a.pdf",
        homework_file_url="https://cdn-emis.edu.uz/files/b.pdf",
        video_url="https://www.youtube.com/watch?v=q0sUmfmG7gI",
    )
    env.emis.classes = [
        klass(0, 2, kind="midterm", topic=files),
        klass(1, 2, topic=files),
    ]

    result = await run(env, group.id, user.id)

    first = await lesson_on(env, day(0, 2))
    assert first.kind == "midterm"  # the kind still comes
    assert (first.topic, first.emis_topic) == (None, None)
    assert (await lesson_on(env, day(1, 2))).topic is None
    assert env.urls.attached == {} and env.urls.calls == 0
    assert result.resources == 0


async def test_the_emis_topic_is_stored_when_topics_are_switched_on(
    topics_env: Env,
) -> None:
    """ACA-7: with EMIS__IMPORT_TOPICS the topic is stored and marked as EMIS's."""
    env = topics_env
    _, group, user = await set_up(env)
    env.emis.classes = [
        klass(0, 2, 0, kind="lecture", class_id=111, topic=topic()),
        klass(1, 2, 0, kind="midterm", class_id=112),
    ]

    await run(env, group.id, user.id)

    first, second = await lesson_on(env, day(0, 2)), await lesson_on(env, day(1, 2))
    assert (first.kind, first.emis_class_id, first.topic) == ("lecture", 111, "Jadids")
    assert first.emis_topic == "Jadids"
    assert (second.kind, second.emis_class_id, second.topic) == ("midterm", 112, None)


async def test_the_emis_topic_follows_emis_until_a_teacher_writes_their_own(
    topics_env: Env,
) -> None:
    """ACA-7: a topic the teacher set is never replaced by EMIS's."""
    env = topics_env
    _, group, user = await set_up(env)
    env.emis.classes = [
        klass(0, 2, topic=topic()),
        klass(1, 2, topic=topic()),
        klass(2, 2),
    ]
    await run(env, group.id, user.id)
    teacher_topic = await lesson_on(env, day(1, 2))
    teacher_topic.topic = "Our own title"
    async with env.uow_factory() as uow:
        await uow.lessons.save(teacher_topic)
        await uow.commit()
    env.emis.classes = [
        klass(0, 2, topic=EmisTopic(name="Reworded")),
        klass(1, 2, topic=EmisTopic(name="Reworded")),
        klass(2, 2, topic=EmisTopic(name="Third")),
    ]

    await run(env, group.id, user.id)

    assert (await lesson_on(env, day(0, 2))).topic == "Reworded"
    assert (await lesson_on(env, day(1, 2))).topic == "Our own title"
    assert (await lesson_on(env, day(1, 2))).emis_topic == "Reworded"
    assert (await lesson_on(env, day(2, 2))).topic == "Third"


async def test_topic_files_become_resources_once(topics_env: Env) -> None:
    """ACA-9: file, homework file and video are attached once, with the topic's name."""
    env = topics_env
    _, group, user = await set_up(env)
    files = topic(
        topic_file_url="https://cdn-emis.edu.uz/files/a.pdf",
        homework_file_url="https://cdn-emis.edu.uz/files/b.pdf",
        video_url="https://www.youtube.com/watch?v=q0sUmfmG7gI",
    )
    env.emis.classes = [klass(0, 2, topic=files), klass(1, 2, topic=topic())]

    first = await run(env, group.id, user.id)
    second = await run(env, group.id, user.id)

    lesson = await lesson_on(env, day(0, 2))
    attached = env.urls.of(lesson.id)
    assert [(a.url, a.title) for a in attached] == [
        ("https://cdn-emis.edu.uz/files/a.pdf", "Jadids"),
        ("https://cdn-emis.edu.uz/files/b.pdf", "Jadids (homework)"),
        ("https://www.youtube.com/watch?v=q0sUmfmG7gI", "Jadids (video)"),
    ]
    assert (first.resources, second.resources) == (3, 0)
    assert env.urls.of((await lesson_on(env, day(1, 2))).id) == []


# - - - the second run - - -


async def test_running_twice_changes_nothing(env: Env) -> None:
    """ACA-1: a repeated task, or a second student of the group, adds nothing."""
    term, group, user = await set_up(env)
    env.emis.classes = (
        weekly(2, 0, topic=topic())
        + weekly(3, 1, subject=PHYSICS)
        + weekly(6, 0, weeks=(1, 3), subject=HISTORY)
    )
    await run(env, group.id, user.id)
    entries = await entries_of(env, term.id)
    lessons = await lessons_of(env)
    people = len(env.identity.users)

    again = await run(env, group.id, user.id)

    assert (again.entries, again.merged, again.updated, again.removed) == (0, 0, 0, 0)
    assert again.lessons == 0 and again.resources == 0
    assert [e.id for e in await entries_of(env, term.id)] == [e.id for e in entries]
    assert await lessons_of(env) == lessons
    assert len(env.identity.users) == people


async def test_a_changed_teacher_updates_the_entry_and_future_lessons_in_place(
    env: Env,
) -> None:
    """ACA-7: the entry keeps its id; lessons not started take the new teacher."""
    term, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0)
    await run(env, group.id, user.id)
    [entry] = await entries_of(env, term.id)
    env.emis.classes = weekly(2, 0, teacher=YULDASHEV, room="305")

    result = await run(env, group.id, user.id)

    [after] = await entries_of(env, term.id)
    assert (result.updated, result.entries, result.removed) == (1, 0, 0)
    assert after.id == entry.id and after.teacher_id != entry.teacher_id
    future = [x for x in await lessons_of(env) if x.date > TODAY]
    assert future and {x.teacher_id for x in future} == {after.teacher_id}
    assert {x.room_id for x in future} == {after.room_id}


async def test_a_slot_that_leaves_emis_removes_the_entry_and_its_empty_lessons(
    env: Env,
) -> None:
    """ACA-7: lessons with homework are cancelled, empty future ones deleted."""
    term, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0) + weekly(3, 0, subject=PHYSICS)
    await run(env, group.id, user.id)
    with_homework = await lesson_on(env, day(1, 3))
    await env.give_homework(with_homework.id)
    env.emis.classes = weekly(2, 0)

    result = await run(env, group.id, user.id)

    assert result.removed == 1
    assert [(e.weekday, e.period) for e in await entries_of(env, term.id)] == [(2, 1)]
    wednesdays = [x for x in await lessons_of(env) if x.date.isoweekday() == 3]
    assert [(x.date, x.status) for x in wednesdays] == [(day(1, 3), "cancelled")]


async def test_a_shared_entry_is_split_when_one_group_changes_its_lesson(
    env: Env,
) -> None:
    """ACA-6: group B's new teacher takes B out of the lesson it shared with A."""
    term = await env.term()
    first = await env.group("2TN2", emis_group_id=3292)
    second = await env.group("1TN1", emis_group_id=3291)
    one, two = await env.student(first), await env.student(second, first_name="Bobur")
    env.emis.by_user = {one.id: weekly(2, 0), two.id: weekly(2, 0)}
    await run(env, first.id, one.id)
    merged = await run(env, second.id, two.id)
    assert (merged.entries, merged.merged) == (0, 1)
    [shared] = await entries_of(env, term.id)
    env.emis.by_user[two.id] = weekly(2, 0, teacher=YULDASHEV, room="204")

    await run(env, second.id, two.id)

    entries = await entries_of(env, term.id)
    assert len(entries) == 2
    by_group = {tuple(e.audience): e for e in entries}
    assert by_group[(str(first.id),)].id == shared.id
    assert by_group[(str(second.id),)].teacher_id != shared.teacher_id


# - - - moved, cancelled and added classes - - -


async def test_a_moved_class_takes_its_lesson_along(env: Env) -> None:
    """ACA-7: the class id follows EMIS; homework and attendance stay with it."""
    _, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0) + weekly(4, 0, subject=PHYSICS)
    await run(env, group.id, user.id)
    lesson = await lesson_on(env, day(1, 2))
    await env.give_homework(lesson.id)
    moved = klass(1, 3, 1, class_id=lesson.emis_class_id)
    env.emis.classes = (
        [moved]
        + [c for c in weekly(2, 0) if c.date != day(1, 2)]
        + weekly(4, 0, subject=PHYSICS)
    )

    result = await run(env, group.id, user.id)

    after = await env.reader.lesson_view(lesson.id, "ru")
    assert after is not None
    stored = [x for x in await lessons_of(env) if x.id == lesson.id][0]
    assert (stored.date, stored.period) == (day(1, 3), 2)
    assert stored.is_overridden and stored.status == "scheduled"
    assert stored.changes is not None and set(stored.changes) == {"date", "time"}
    assert stored.emis_class_id == lesson.emis_class_id
    assert result.lessons >= 1
    assert not [
        x for x in await lessons_of(env) if (x.date, x.period) == (day(1, 2), 1)
    ]


async def test_a_class_that_disappears_is_cancelled_and_comes_back_when_it_returns(
    env: Env,
) -> None:
    """ACA-7: EMIS cancels a lesson it listed before; listing it again undoes that."""
    _, group, user = await set_up(env)
    listed = weekly(2, 0)
    env.emis.classes = listed
    await run(env, group.id, user.id)
    env.emis.classes = [c for c in listed if c.date != day(1, 2)]

    await run(env, group.id, user.id)

    cancelled = await lesson_on(env, day(1, 2))
    assert cancelled.status == "cancelled" and cancelled.is_overridden
    assert cancelled.changes == {"status": ["scheduled", "cancelled"]}
    assert cancelled.emis_class_id is not None
    env.emis.classes = listed

    await run(env, group.id, user.id)

    back = await lesson_on(env, day(1, 2))
    assert (back.status, back.changes, back.is_overridden) == ("scheduled", None, False)


async def test_a_lesson_edited_by_hand_is_left_alone(env: Env) -> None:
    """ACA-7: a change made by Administration is not undone by EMIS."""
    from app.modules.academic.application.schedule.update_lesson import LessonPatch
    from tests.factories import make_actor

    _, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0, topic=topic())
    await run(env, group.id, user.id)
    lesson = await lesson_on(env, day(1, 2))
    await env.services.update_lesson.execute(
        make_actor(Role.ADMIN), lesson.id, LessonPatch(room_name="Lab")
    )
    env.emis.classes = [c for c in env.emis.classes if c.date != day(1, 2)]

    await run(env, group.id, user.id)

    edited = await lesson_on(env, day(1, 2))
    assert edited.status == "scheduled" and edited.emis_class_id is None
    assert edited.changes is not None and "room" in edited.changes


async def test_an_added_class_becomes_an_extra_lesson_from_today_on(env: Env) -> None:
    """ACA-7: a midterm that no weekly entry produces; days gone by get none."""
    _, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0) + [
        klass(1, 4, 2, kind="midterm", subject=HISTORY, class_id=777),
        klass(0, 1, 3, subject=HISTORY, class_id=778),  # Monday 5 Oct: over
    ]

    await run(env, group.id, user.id)

    midterm = await lesson_on(env, day(1, 4), 3)
    assert midterm.kind == "midterm" and midterm.emis_class_id == 777
    assert midterm.timetable_entry_id is None and midterm.audience == [str(group.id)]
    assert not [x for x in await lessons_of(env) if x.date == day(0, 1)]


async def test_a_class_of_a_day_gone_by_only_enriches_an_existing_lesson(
    topics_env: Env,
) -> None:
    """ACA-7: topic and kind of yesterday's lesson arrive, no lesson is invented."""
    env = topics_env
    term, group, user = await set_up(env)
    subject = await env.subject("Математика", emis_id=101)
    monday = await env.lesson(
        term, day=day(0, 1), period=1, subject=subject, audience=[str(group.id)]
    )
    env.emis.classes = [
        klass(0, 1, kind="practice", topic=topic(), class_id=500),
        klass(0, 1, 4, subject=HISTORY, class_id=501),
    ]

    await run(env, group.id, user.id)

    stored = await lesson_on(env, day(0, 1))
    assert stored.id == monday.id
    assert (stored.kind, stored.topic) == ("practice", "Jadids")
    on_that_day = [x for x in await lessons_of(env) if x.date == day(0, 1)]
    assert [x.id for x in on_that_day] == [monday.id]  # none made for pair 5


async def test_hand_made_entries_and_their_lessons_are_not_touched(env: Env) -> None:
    """ACA-1: EMIS decides only for entries it made itself."""
    term, group, user = await set_up(env)
    subject = await env.subject("Физика", emis_id=102)
    manual = await env.entry(
        term, weekday=4, period=1, subject=subject, audience=[str(group.id)]
    )
    env.emis.classes = weekly(2, 0)
    await run(env, group.id, user.id)
    env.emis.classes = []  # EMIS lists nothing now

    emptied = await run(env, group.id, user.id)

    assert emptied.status == "empty"
    env.emis.classes = weekly(2, 0, subject=HISTORY)
    await run(env, group.id, user.id)
    entries = await entries_of(env, term.id)
    assert manual.id in {e.id for e in entries}
    assert next(e for e in entries if e.id == manual.id).source == "manual"
    thursdays = [x for x in await lessons_of(env) if x.date.isoweekday() == 4]
    assert thursdays and all(x.status == "scheduled" for x in thursdays)


async def test_a_slot_that_clashes_with_a_hand_made_entry_is_skipped(env: Env) -> None:
    """ACA-8: EMIS never overrides a hand-made entry; the row is skipped, not failed."""
    term, group, user = await set_up(env)
    subject = await env.subject("Физика", emis_id=102)
    teacher = env.teacher("Gulnora", "Kalandarova")
    await env.entry(
        term,
        weekday=2,
        period=1,
        subject=subject,
        audience=[str(group.id)],
        teacher=teacher,
    )
    env.emis.classes = weekly(2, 0)

    result = await run(env, group.id, user.id)

    assert (result.entries, result.skipped) == (0, 1)
    assert len(await entries_of(env, term.id)) == 1


# - - - nothing to do and errors - - -


@pytest.mark.parametrize("error", [EmisUnavailable(), EmisAuthFailed()])
async def test_emis_errors_leave_everything_as_it_was(
    env: Env, error: Exception
) -> None:
    """ID-7: a failing link is a status, so another student can be tried."""
    term, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0)
    await run(env, group.id, user.id)
    entries = await entries_of(env, term.id)
    env.emis.timetable_error = error

    result = await run(env, group.id, user.id)

    assert result.status == "emis_unavailable"
    assert [e.id for e in await entries_of(env, term.id)] == [e.id for e in entries]


async def test_a_run_for_nothing_to_import_is_not_an_error(env: Env) -> None:
    """ACA-1: no term, no group, a student of another group, an empty answer."""
    group = await env.group("2TN2", emis_group_id=3292)
    user = await env.student(group)
    assert (await run(env, group.id, user.id)).status == "no_term"

    await env.term()
    assert (await run(env, group.id, user.id)).status == "empty"

    env.emis.classes = weekly(2, 0)
    other = await env.group("1TN1", emis_group_id=3291)
    assert (await run(env, other.id, user.id)).status == "no_student"
    assert (await run(env, UUID(int=5), user.id)).status == "no_group"


async def test_a_deactivated_teacher_leaves_the_lessons_unassigned(env: Env) -> None:
    """ACA-7: 'teacher needed' until Administration picks someone."""
    term, group, user = await set_up(env)
    env.identity.add(make_gone_teacher("Gulnora", "Kalandarova"))
    env.emis.classes = weekly(2, 0)

    await run(env, group.id, user.id)

    [entry] = await entries_of(env, term.id)
    assert entry.teacher_id is None


async def test_the_audit_trail_records_the_sync(env: Env) -> None:
    """ACA-1: Administration can see where the timetable came from."""
    _, group, user = await set_up(env)
    env.emis.classes = weekly(2, 0)

    await run(env, group.id, user.id)

    event = next(a for a in env.audits if a.type == "group.timetable_synced")
    assert event.metadata is not None
    assert event.metadata["group_id"] == str(group.id)
    assert (event.metadata["added"], event.metadata["source"]) == (1, "emis")


def make_gone_teacher(first: str, last: str):  # type: ignore[no-untyped-def]
    from tests.fakes.academic.schedule.identity import make_user

    return make_user(
        first_name=first,
        last_name=last,
        roles=frozenset({Role.TEACHER}),
        status=UserStatus.DEACTIVATED,
    )
