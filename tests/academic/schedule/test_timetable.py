"""Weekly timetable: entries, conflicts, copying (ADM-9, ACA-5, ACA-6, ACA-8)."""

import datetime as dt

from app.modules.academic.application.schedule.entry_builder import EntryInput
from app.modules.academic.application.schedule.update_entry import EntryPatch
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.errors import (
    EntryInvalidError,
    EntryNotFoundError,
    GroupNotFoundError,
    SubjectNotFoundError,
    TermNotFoundError,
)
from app.modules.academic.domain.schedule.lesson import Lesson
from app.shared.actor import Role
from app.shared.base_error import ConflictError
from app.shared.ids import new_id
from tests.academic.schedule.builders import entry_input
from tests.academic.schedule.env import Env
from tests.factories import make_actor

import pytest

ADMIN = make_actor(Role.ADMIN)


async def test_an_entry_is_created_with_its_room_and_triggers_generation(
    env: Env,
) -> None:
    """UF-ADM-06: saving an entry creates the room and regenerates lessons."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group("2TN2")
    teacher = env.teacher()

    created = await env.services.create_entry.execute(
        ADMIN,
        entry_input(
            term.id, subject.id, group.id, teacher_id=teacher.id, room_name="Кластер"
        ),
    )

    assert created.subject.name == "Математика" and created.subject.short_name == "Мат"
    assert created.teacher is not None and created.teacher.id == teacher.id
    assert created.room is not None and created.room.slug == "klaster"
    assert [(a.group_name, a.subgroup) for a in created.audience] == [("2TN2", None)]
    assert env.kicker.calls == [
        (
            "academic.generate_lessons",
            {"term_id": str(term.id), "from_date": "2026-10-06"},
        )
    ]


async def test_the_same_teacher_cannot_teach_two_groups_at_once(env: Env) -> None:
    """ACA-8: a conflict is rejected with the list of conflicts."""
    term = await env.term()
    subject = await env.subject()
    first = await env.group("2TN1")
    second = await env.group("2TN2")
    teacher = env.teacher()
    existing = await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, first.id, teacher_id=teacher.id)
    )

    with pytest.raises(ConflictError) as caught:
        await env.services.create_entry.execute(
            ADMIN, entry_input(term.id, subject.id, second.id, teacher_id=teacher.id)
        )

    conflicts = caught.value.params["conflicts"]
    assert [c["kind"] for c in conflicts] == ["teacher"]
    assert conflicts[0]["with_entry_id"] == str(existing.id)
    assert caught.value.code == "common/conflict" and caught.value.status == 409
    async with env.uow_factory() as uow:
        assert len(await uow.entries.list_for_term(term.id)) == 1


async def test_a_conflicting_entry_does_not_create_its_room(env: Env) -> None:
    """ACA-8: a rejected save leaves no half-made room behind."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id)
    )

    with pytest.raises(ConflictError):
        await env.services.create_entry.execute(
            ADMIN, entry_input(term.id, subject.id, group.id, room_name="Lab")
        )

    async with env.uow_factory() as uow:
        assert await uow.rooms.get_by_slug("lab") is None


async def test_a_whole_group_lesson_conflicts_with_its_subgroup(env: Env) -> None:
    """ACA-6: a group lesson occupies both subgroups."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id)
    )

    with pytest.raises(ConflictError) as caught:
        await env.services.create_entry.execute(
            ADMIN, entry_input(term.id, subject.id, group.id, subgroup=1)
        )

    assert [c["kind"] for c in caught.value.params["conflicts"]] == ["audience"]


async def test_subgroups_can_have_different_lessons_at_the_same_time(env: Env) -> None:
    """ACA-2: subgroup 1 and subgroup 2 of one group do not conflict."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id, subgroup=1)
    )

    second = await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id, subgroup=2)
    )

    assert [(a.subgroup) for a in second.audience] == [2]


async def test_odd_and_even_weeks_share_a_slot(env: Env) -> None:
    """ACA-5: parity splits a slot between two entries."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    await env.services.create_entry.execute(
        ADMIN,
        entry_input(term.id, subject.id, group.id, teacher_id=teacher.id, parity="odd"),
    )

    other = await env.services.create_entry.execute(
        ADMIN,
        entry_input(
            term.id, subject.id, group.id, teacher_id=teacher.id, parity="even"
        ),
    )

    assert other.week_parity == "even"


async def test_checking_an_entry_reports_conflicts_and_saves_nothing(env: Env) -> None:
    """UF-ADM-06 step 3: conflicts are shown at once."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id, teacher_id=teacher.id)
    )

    conflicts = await env.services.check_entry.execute(
        entry_input(
            term.id, subject.id, group.id, teacher_id=teacher.id, room_name="Lab"
        )
    )

    assert [c.kind for c in conflicts] == ["teacher", "audience"]
    async with env.uow_factory() as uow:
        assert len(await uow.entries.list_for_term(term.id)) == 1
        assert await uow.rooms.get_by_slug("lab") is None
    assert len(env.kicker.calls) == 1  # only the first create kicked generation


async def test_checking_an_existing_room_finds_room_conflicts(env: Env) -> None:
    """ACA-8: a room used by another group at the same time is reported."""
    term = await env.term()
    subject = await env.subject()
    first = await env.group("2TN1")
    second = await env.group("2TN2")
    await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, first.id, room_name="102")
    )

    conflicts = await env.services.check_entry.execute(
        entry_input(term.id, subject.id, second.id, room_name=" 102")
    )

    assert [c.kind for c in conflicts] == ["room"]


async def test_checking_an_entry_ignores_the_entry_being_edited(env: Env) -> None:
    """UF-ADM-06: editing a cell does not conflict with itself."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    saved = await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id)
    )

    conflicts = await env.services.check_entry.execute(
        entry_input(term.id, subject.id, group.id), entry_id=saved.id
    )

    assert conflicts == []


async def test_an_entry_needs_an_existing_term_subject_and_groups(env: Env) -> None:
    """ACA-5: references are checked."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()

    with pytest.raises(TermNotFoundError):
        await env.services.create_entry.execute(
            ADMIN, entry_input(new_id(), subject.id, group.id)
        )
    with pytest.raises(SubjectNotFoundError):
        await env.services.create_entry.execute(
            ADMIN, entry_input(term.id, new_id(), group.id)
        )
    with pytest.raises(GroupNotFoundError):
        await env.services.create_entry.execute(
            ADMIN, entry_input(term.id, subject.id, new_id())
        )


async def test_an_entry_without_audience_is_invalid(env: Env) -> None:
    """ACA-6: a lesson needs an audience."""
    term = await env.term()
    subject = await env.subject()
    bad = EntryInput(
        term.id, 1, 1, "every", subject.id, None, None, [], dt.date(2026, 9, 1), None
    )

    with pytest.raises(EntryInvalidError):
        await env.services.create_entry.execute(ADMIN, bad)


async def test_updating_changes_only_the_sent_fields(env: Env) -> None:
    """UF-ADM-06 5a: change the room, keep the rest."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    saved = await env.services.create_entry.execute(
        ADMIN,
        entry_input(
            term.id, subject.id, group.id, teacher_id=teacher.id, room_name="102"
        ),
    )
    env.kicker.calls.clear()

    updated = await env.services.update_entry.execute(
        ADMIN, saved.id, EntryPatch(room_name="103")
    )

    assert updated.room is not None and updated.room.slug == "103"
    assert updated.teacher is not None and updated.teacher.id == teacher.id
    assert (updated.weekday, updated.period) == (1, 1)
    assert env.kicker.names() == ["academic.generate_lessons"]


async def test_a_patch_can_clear_the_teacher_and_the_room(env: Env) -> None:
    """API: null clears a nullable field."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    saved = await env.services.create_entry.execute(
        ADMIN,
        entry_input(
            term.id, subject.id, group.id, teacher_id=env.teacher().id, room_name="102"
        ),
    )

    updated = await env.services.update_entry.execute(
        ADMIN, saved.id, EntryPatch(teacher_id=None, room_name=None)
    )

    assert updated.teacher is None and updated.room is None


async def test_updating_into_a_conflict_is_rejected(env: Env) -> None:
    """ACA-8: moving an entry onto a busy slot fails with the conflicts."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id)
    )
    movable = await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id, period=2)
    )

    with pytest.raises(ConflictError):
        await env.services.update_entry.execute(ADMIN, movable.id, EntryPatch(period=1))


async def test_updating_an_unknown_entry_is_not_found(env: Env) -> None:
    """API: unknown ids answer 404."""
    with pytest.raises(EntryNotFoundError):
        await env.services.update_entry.execute(ADMIN, new_id(), EntryPatch(period=2))


async def test_deleting_an_entry_tidies_its_future_lessons(env: Env) -> None:
    """ACA-7: empty future lessons go, homework lessons are cancelled, past stays."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    entry = await env.entry(
        term, weekday=1, period=1, subject=subject, audience=audience
    )

    async def lesson(day: dt.date, *, overridden: bool = False) -> Lesson:
        return await env.lesson(
            term,
            day=day,
            period=1,
            subject=subject,
            audience=audience,
            entry=entry,
            overridden=overridden,
        )

    past = await lesson(dt.date(2026, 10, 5))
    empty = await lesson(dt.date(2026, 10, 12))
    homework = await lesson(dt.date(2026, 10, 19))
    by_hand = await lesson(dt.date(2026, 10, 26), overridden=True)
    await env.give_homework(homework.id)

    await env.services.delete_entry.execute(entry.id)

    lessons = {x.id: x for x in await env.lessons()}
    assert empty.id not in lessons
    assert lessons[homework.id].status == "cancelled"
    assert lessons[past.id].status == "scheduled"
    assert lessons[by_hand.id].status == "scheduled"
    assert all(x.timetable_entry_id is None for x in lessons.values())
    async with env.uow_factory() as uow:
        assert await uow.entries.get(entry.id) is None
    recompute = [
        kw for name, kw in env.kicker.calls if name == "academic.recompute_due_dates"
    ]
    assert recompute and set(recompute[0]["lesson_ids"]) == {
        str(empty.id),
        str(homework.id),
    }


async def test_deleting_an_unknown_entry_is_not_found(env: Env) -> None:
    """API: unknown ids answer 404."""
    with pytest.raises(EntryNotFoundError):
        await env.services.delete_entry.execute(new_id())


async def test_copying_a_timetable_into_the_next_term(env: Env) -> None:
    """UF-ADM-06 step 4: copy last term's timetable and adjust it."""
    old = await env.term()
    new = await env.term(
        starts_on=dt.date(2027, 1, 11),
        ends_on=dt.date(2027, 5, 30),
        academic_year="2026-2027",
        half=2,
    )
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    room = await env.room("102")
    await env.entry(
        old,
        weekday=1,
        period=1,
        subject=subject,
        audience=[str(group.id)],
        teacher=teacher,
        room=room,
    )
    await env.entry(  # replaced during the term, so it is not copied
        old,
        weekday=2,
        period=1,
        subject=subject,
        audience=[str(group.id)],
        valid_to=dt.date(2026, 10, 31),
    )

    created = await env.services.copy_timetable.execute(old.id, new.id)

    assert created == 1
    copied = await env.services.list_entries.execute(ADMIN, term_id=new.id)
    assert len(copied) == 1
    assert copied[0].valid_from == dt.date(2027, 1, 11) and copied[0].valid_to is None
    assert copied[0].room is not None and copied[0].room.id == room.id
    assert env.kicker.calls[-1] == (
        "academic.generate_lessons",
        {"term_id": str(new.id), "from_date": "2026-10-06"},
    )


async def test_copying_skips_entries_that_would_conflict(env: Env) -> None:
    """ADM-9: the target term may already have entries."""
    old = await env.term()
    new = await env.term(
        starts_on=dt.date(2027, 1, 11), ends_on=dt.date(2027, 5, 30), half=2
    )
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    await env.entry(old, weekday=1, period=1, subject=subject, audience=audience)
    await env.entry(old, weekday=1, period=2, subject=subject, audience=audience)
    await env.entry(new, weekday=1, period=1, subject=subject, audience=audience)

    created = await env.services.copy_timetable.execute(old.id, new.id)

    assert created == 1


async def test_a_term_cannot_be_copied_into_itself(env: Env) -> None:
    """ADM-9: copy needs two different terms."""
    term = await env.term()

    with pytest.raises(EntryInvalidError):
        await env.services.copy_timetable.execute(term.id, term.id)


async def test_entries_are_listed_by_group_teacher_or_room(env: Env) -> None:
    """ADM-9: the grid is per group, teacher or room (default: the current term)."""
    term = await env.term()
    subject = await env.subject()
    first = await env.group("2TN1")
    second = await env.group("2TN2")
    teacher = env.teacher()
    room = await env.room("102")
    await env.entry(
        term,
        weekday=2,
        period=1,
        subject=subject,
        audience=[str(first.id)],
        teacher=teacher,
    )
    await env.entry(
        term, weekday=1, period=1, subject=subject, audience=[str(second.id)], room=room
    )
    await env.entry(
        term,
        weekday=1,
        period=2,
        subject=subject,
        audience=[audience_keys.key(second.id, 1)],
    )

    everything = await env.services.list_entries.execute(ADMIN)
    by_group = await env.services.list_entries.execute(ADMIN, group_id=second.id)
    by_teacher = await env.services.list_entries.execute(ADMIN, teacher_id=teacher.id)
    by_room = await env.services.list_entries.execute(ADMIN, room_id=room.id)

    assert [(e.weekday, e.period) for e in everything] == [(1, 1), (1, 2), (2, 1)]
    assert [(e.weekday, e.period) for e in by_group] == [(1, 1), (1, 2)]
    assert [e.weekday for e in by_teacher] == [2]
    assert [e.room.slug for e in by_room if e.room] == ["102"]


async def test_listing_without_any_term_is_empty(env: Env) -> None:
    """ADM-9: nothing to show before the first term exists."""
    assert await env.services.list_entries.execute(ADMIN) == []
