"""ACA-1, ACA-5, ACA-6, ACA-7, ID-10: an unknown group is filled from EMIS."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.modules.academic.application.schedule.bootstrap_group import BootstrapResult
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.shared.actor import Role
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisTeacher,
    EmisTimetableItem,
    EmisUnavailable,
)
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from tests.academic.schedule.env import Env
from tests.fakes.academic.schedule.identity import make_user

STUDENT = new_id()
MATH = EmisTeacher(9001, "GULNORA", "KALANDAROVA", "AKBAROVNA")
LANGUAGES = EmisTeacher(9002, "SARDOR", "YULDASHEV", None)
UZBEK = EmisTeacher(9003, "MADINA", "ISMOILOVA", None)


def item(
    weekday: int,
    pair: int,
    subject_id: int | None,
    name: str,
    teacher: EmisTeacher | None,
    room: str | None,
    *,
    subgroup: Literal[1, 2] | None = None,
    parity: Literal["every", "odd", "even"] = "every",
) -> EmisTimetableItem:
    return EmisTimetableItem(
        weekday, pair, subject_id, name, teacher, room, subgroup, parity
    )


async def entries_of(env: Env, term_id: UUID) -> list[TimetableEntry]:
    async with env.uow_factory() as uow:
        found = await uow.entries.list_for_term(term_id)
    return sorted(found, key=lambda e: (e.weekday, e.period, e.audience))


async def run(env: Env, group_id: UUID, user_id: UUID = STUDENT) -> BootstrapResult:
    return await env.emis_import.bootstrap_group.execute(
        group_id=group_id, user_id=user_id
    )


async def test_an_unknown_groups_timetable_becomes_entries_rooms_teachers_and_lessons(
    env: Env,
) -> None:
    """ACA-1: entries, rooms, teachers and lessons with the EMIS bell times."""
    term = await env.term()
    math = await env.subject("Математика", emis_id=101)
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [
        item(3, 0, 101, "Mathematics", MATH, "101"),
        item(3, 1, 103, "English", LANGUAGES, "204", subgroup=1),
        item(3, 1, 103, "English", UZBEK, "Кластер", subgroup=2),
        item(6, 0, 106, "History", MATH, "101", parity="odd"),
    ]

    result = await run(env, group.id)

    assert result.status == "imported"
    assert (result.entries, result.merged, result.skipped) == (4, 0, 0)
    assert result.teachers == 3 and result.lessons > 0
    entries = await entries_of(env, term.id)
    assert [(e.weekday, e.period, e.week_parity) for e in entries] == [
        (3, 1, "every"),
        (3, 2, "every"),
        (3, 2, "every"),
        (6, 1, "odd"),
    ]
    assert math.id in {e.subject_id for e in entries}
    halves = sorted(e.audience[0] for e in entries if e.period == 2)
    assert halves == [f"{group.id}:1", f"{group.id}:2"]
    assert {e.teacher_id for e in entries if e.period == 2} != {None}
    async with env.uow_factory() as uow:
        assert await uow.rooms.get_by_slug("101") is not None
        assert await uow.rooms.get_by_slug("klaster") is not None


async def test_lessons_start_and_end_at_the_emis_bell_times(env: Env) -> None:
    """ACA-4, ACA-7: the first pair is 08:30-09:50, Tashkent time."""
    await env.term()
    await env.subject("Математика", emis_id=101)
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]

    await run(env, group.id)

    lessons = await env.lessons()
    assert [x.date for x in lessons] == [dt.date(2026, 10, 7), dt.date(2026, 10, 14)]
    assert lessons[0].starts_at == dt.datetime(2026, 10, 7, 3, 30, tzinfo=dt.UTC)
    assert lessons[0].ends_at == dt.datetime(2026, 10, 7, 4, 50, tzinfo=dt.UTC)
    assert lessons[0].audience == [str(group.id)] and lessons[0].period == 1


async def test_teachers_are_created_once_without_activation_or_an_email(
    env: Env,
) -> None:
    """ID-10: pending staff accounts named from EMIS, one per teacher."""
    await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [
        item(3, 0, 101, "Mathematics", MATH, "101"),
        item(4, 0, 102, "Physics", MATH, "101"),
        item(4, 1, 103, "English", LANGUAGES, "204"),
    ]

    await run(env, group.id)

    made = [
        u
        for u in env.identity.users.values()
        if u.status is UserStatus.PENDING_ACTIVATION
    ]
    assert sorted(u.last_name for u in made) == ["KALANDAROVA", "YULDASHEV"]
    assert all(Role.TEACHER in u.roles for u in made)
    assert [t["emis_teacher_id"] for t in env.commands.teachers].count(9001) == 1


async def test_an_existing_teacher_is_reused(env: Env) -> None:
    """ACA-1: a teacher Administration already created is matched, not duplicated."""
    term = await env.term()
    known = env.teacher("Gulnora", "Kalandarova")
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]

    await run(env, group.id)

    assert [e.teacher_id for e in await entries_of(env, term.id)] == [known.id]
    assert len(env.identity.users) == 1


async def test_a_second_run_for_the_same_group_adds_nothing(env: Env) -> None:
    """ACA-1: a second student of the group, or a repeated task, is a no-op."""
    term = await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [
        item(3, 0, 101, "Mathematics", MATH, "101"),
        item(3, 1, 103, "English", LANGUAGES, "204", subgroup=1),
    ]
    first = await run(env, group.id)
    entries = await entries_of(env, term.id)
    lessons = await env.lessons()
    users = len(env.identity.users)
    env.emis.calls.clear()

    second = await run(env, group.id, user_id=new_id())

    assert (first.status, second.status) == ("imported", "exists")
    assert [e.id for e in await entries_of(env, term.id)] == [e.id for e in entries]
    assert [x.id for x in await env.lessons()] == [x.id for x in lessons]
    assert len(env.identity.users) == users
    assert env.emis.calls == []  # not even asked


async def test_a_group_with_a_timetable_made_by_hand_is_left_alone(env: Env) -> None:
    """ACA-5: Administration's own entries are never mixed with EMIS's."""
    term = await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    subject = await env.subject()
    await env.entry(
        term, weekday=1, period=1, subject=subject, audience=[str(group.id)]
    )
    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]

    result = await run(env, group.id)

    assert result.status == "exists"
    assert len(await entries_of(env, term.id)) == 1


async def test_two_groups_sharing_a_lesson_become_one_merged_entry(env: Env) -> None:
    """ACA-6: the same lesson in two groups' timetables is one entry, two groups."""
    term = await env.term()
    first = await env.group("2TN2", emis_group_id=3292)
    second = await env.group("1TN1", emis_group_id=3291)
    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]
    await run(env, first.id)

    merged = await run(env, second.id)

    assert (merged.status, merged.entries, merged.merged) == ("imported", 0, 1)
    entries = await entries_of(env, term.id)
    assert len(entries) == 1
    assert sorted(entries[0].audience) == sorted([str(first.id), str(second.id)])
    assert len(await env.lessons()) == 2


async def test_a_clashing_row_is_skipped_and_the_others_are_imported(
    env: Env,
) -> None:
    """ACA-8: a teacher in two places is reported, not allowed; no failure."""
    term = await env.term()
    first = await env.group("2TN2", emis_group_id=3292)
    second = await env.group("1TN1", emis_group_id=3291)
    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]
    await run(env, first.id)
    env.emis.items = [
        item(3, 0, 102, "Physics", MATH, "102"),  # same teacher, same time
        item(3, 1, 103, "English", LANGUAGES, "204"),
    ]

    result = await run(env, second.id)

    assert (result.status, result.entries, result.skipped) == ("imported", 1, 1)
    assert len(await entries_of(env, term.id)) == 2


async def test_rows_that_cannot_be_placed_are_skipped(env: Env) -> None:
    """ACA-5: Sunday, a negative pair or a row without a subject name."""
    term = await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [
        item(7, 0, 101, "Mathematics", MATH, "101"),
        item(3, -1, 101, "Mathematics", MATH, "101"),
        item(3, 0, None, " ", MATH, "101"),
        item(3, 2, 101, "Mathematics", MATH, None),
    ]

    result = await run(env, group.id)

    assert (result.entries, result.skipped) == (1, 3)
    only = (await entries_of(env, term.id))[0]
    assert (only.weekday, only.period, only.room_id) == (3, 3, None)


async def test_subjects_are_found_by_emis_id_then_by_name_and_created_last(
    env: Env,
) -> None:
    """ACA-1: the curriculum's subjects are reused; others are created."""
    term = await env.term()
    by_id = await env.subject("Математика", emis_id=101)
    by_name = await env.subject("Физика", emis_id=None)
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [
        item(3, 0, 101, "Anything", MATH, "101"),
        item(3, 1, 102, "Физика", MATH, "101"),
        item(3, 2, 107, "Informatics", MATH, "101"),
    ]

    await run(env, group.id)

    subject_ids = [e.subject_id for e in await entries_of(env, term.id)]
    assert subject_ids[:2] == [by_id.id, by_name.id]
    async with env.uow_factory() as uow:
        created = await uow.subjects.get(subject_ids[2])
        adopted = await uow.subjects.get(by_name.id)
    assert created is not None and created.emis_subject_id == 107
    assert set(created.name.values()) == {"Informatics"}
    assert adopted is not None and adopted.emis_subject_id == 102


async def test_a_subject_taught_by_halves_is_marked_as_divisible(env: Env) -> None:
    """ACA-2: a row with a subgroup says the subject is split."""
    await env.term()
    english = await env.subject("English", emis_id=103)
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [item(3, 1, 103, "English", LANGUAGES, "204", subgroup=2)]

    await run(env, group.id)

    async with env.uow_factory() as uow:
        stored = await uow.subjects.get(english.id)
    assert stored is not None and stored.can_be_divided


async def test_a_deactivated_teacher_leaves_the_lesson_unassigned(env: Env) -> None:
    """ACA-7: "teacher needed" until Administration picks someone."""
    term = await env.term()
    env.identity.add(
        make_user(
            first_name="Gulnora",
            last_name="Kalandarova",
            roles=frozenset({Role.TEACHER}),
            status=UserStatus.DEACTIVATED,
        )
    )
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]

    await run(env, group.id)

    assert [e.teacher_id for e in await entries_of(env, term.id)] == [None]


async def test_emis_errors_leave_the_group_untouched_for_the_next_try(
    env: Env,
) -> None:
    """ID-7: an outage or a refused password is reported, nothing half-written."""
    term = await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]

    for error in (EmisUnavailable(), EmisAuthFailed()):
        env.emis.timetable_error = error
        assert (await run(env, group.id)).status == "emis_unavailable"
    env.emis.timetable_error = None
    retried = await run(env, group.id)

    assert retried.status == "imported"
    assert len(await entries_of(env, term.id)) == 1


async def test_unreachable_class_hours_do_not_stop_the_timetable(env: Env) -> None:
    """ACA-4: the bells can be synced later; the entries are not lost."""
    term = await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.hours_error = EmisUnavailable()
    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]

    result = await run(env, group.id)

    assert result.status == "imported"
    assert len(await entries_of(env, term.id)) == 1


async def test_nothing_to_import_is_not_an_error(env: Env) -> None:
    """ACA-1: an empty EMIS timetable, no term, or a group that is gone."""
    group = await env.group("2TN2", emis_group_id=3292)
    assert (await run(env, group.id)).status == "no_term"

    await env.term()
    assert (await run(env, group.id)).status == "empty"

    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]
    assert (await run(env, new_id())).status == "no_group"


async def test_the_import_is_recorded_in_the_audit_trail(env: Env) -> None:
    """ACA-1: Administration can see where the timetable came from."""
    await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    env.emis.items = [item(3, 0, 101, "Mathematics", MATH, "101")]

    await run(env, group.id)

    event = next(a for a in env.audits if a.type == "group.timetable_imported")
    assert event.metadata is not None
    assert event.metadata["group_id"] == str(group.id)
    assert (event.metadata["entries"], event.metadata["source"]) == (1, "emis")
