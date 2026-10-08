"""Pure planning of lesson generation from timetable entries (ACA-7, UF-SYS-05)."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.generation import (
    GenerationPlan,
    expand_entries,
    plan_generation,
)
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.term import MovedDay
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.shared.ids import new_id
from tests.academic.schedule.builders import make_term

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)  # Tue 14:00 in Tashkent
GROUP = new_id()
SUBJECT = new_id()
START = dt.date(2026, 10, 6)
END = dt.date(2026, 10, 19)  # 14 days


def monday_entry(**kwargs: object) -> TimetableEntry:
    """A Monday period-1 entry for the whole group."""
    fields: dict[str, object] = {
        "id": new_id(),
        "term_id": new_id(),
        "weekday": 1,
        "period": 1,
        "week_parity": "every",
        "subject_id": SUBJECT,
        "teacher_id": None,
        "room_id": None,
        "audience": [audience_keys.key(GROUP, None)],
        "valid_from": dt.date(2026, 9, 1),
        "valid_to": None,
    }
    fields.update(kwargs)
    return TimetableEntry(**fields)  # type: ignore[arg-type]


def dates_of(entry: TimetableEntry, **term_kwargs: object) -> list[dt.date]:
    """Return the dates on which an entry produces lessons in the window."""
    term = make_term(**term_kwargs)
    planned = expand_entries(term, [entry], START, END).planned
    return sorted(day for (_, day) in planned)


def test_an_entry_produces_a_lesson_on_each_matching_weekday() -> None:
    """UF-SYS-05: a weekly entry yields one lesson per week of the window."""
    assert dates_of(monday_entry()) == [dt.date(2026, 10, 12), dt.date(2026, 10, 19)]


def test_non_study_days_produce_no_lessons() -> None:
    """ACA-7: no lessons on holidays."""
    assert dates_of(monday_entry(), non_study_days=[dt.date(2026, 10, 12)]) == [
        dt.date(2026, 10, 19)
    ]


def test_a_moved_saturday_uses_the_timetable_of_monday() -> None:
    """ACA-4: Saturday 10.10 follows Monday, so Monday's entry also runs on it."""
    moved = [MovedDay(date=dt.date(2026, 10, 10), follows_weekday=1)]

    days = dates_of(monday_entry(), moved_days=moved)

    assert days == [dt.date(2026, 10, 10), dt.date(2026, 10, 12), dt.date(2026, 10, 19)]


def test_odd_week_entries_run_every_other_week() -> None:
    """ACA-5: parity decides which weeks an entry applies to."""
    odd = dates_of(monday_entry(week_parity="odd"))
    even = dates_of(monday_entry(week_parity="even"))

    assert odd == [dt.date(2026, 10, 12)]  # week 7 counts from Mon 31.08
    assert even == [dt.date(2026, 10, 19)]  # week 8


def test_entries_only_run_inside_their_validity_range() -> None:
    """ACA-5: valid_from and valid_to bound the entry."""
    entry = monday_entry(
        valid_from=dt.date(2026, 10, 13), valid_to=dt.date(2026, 10, 18)
    )

    assert dates_of(entry) == []
    assert dates_of(monday_entry(valid_to=dt.date(2026, 10, 15))) == [
        dt.date(2026, 10, 12)
    ]


def test_the_term_end_stops_generation() -> None:
    """ACA-7: lessons are only generated inside the term."""
    assert dates_of(monday_entry(), ends_on=dt.date(2026, 10, 15)) == [
        dt.date(2026, 10, 12)
    ]


def test_an_entry_without_a_bell_is_skipped_and_reported() -> None:
    """ACA-7: no bell, no lesson (and a warning for the log)."""
    entry = monday_entry(period=9)
    expansion = expand_entries(make_term(), [entry], START, END)

    assert expansion.planned == {}
    assert expansion.missing_bells == {entry.id}


def test_lesson_times_come_from_the_bells_in_utc() -> None:
    """ACA-4: period 1 on Monday is 08:30-09:15 in Tashkent."""
    entry = monday_entry()
    planned = expand_entries(make_term(), [entry], START, END).planned
    first = planned[(entry.id, dt.date(2026, 10, 12))]

    assert first.starts_at == dt.datetime(2026, 10, 12, 3, 30, tzinfo=dt.UTC)
    assert first.ends_at == dt.datetime(2026, 10, 12, 4, 15, tzinfo=dt.UTC)


def existing_lesson(
    entry: TimetableEntry,
    day: dt.date,
    *,
    room: UUID | None = None,
    overridden: bool = False,
    has_content: bool = False,
    starts_at: dt.datetime | None = None,
) -> Lesson:
    """A generated lesson as stored, matching the entry on a day."""
    planned = expand_entries(make_term(id=entry.term_id), [entry], day, day).planned
    item = planned[(entry.id, day)]
    return Lesson(
        id=new_id(),
        term_id=item.term_id,
        date=day,
        period=item.period,
        starts_at=starts_at or item.starts_at,
        ends_at=item.ends_at,
        subject_id=item.subject_id,
        teacher_id=item.teacher_id,
        room_id=room,
        audience=list(item.audience),
        is_overridden=overridden,
        timetable_entry_id=entry.id,
        origin_date=day,
        has_content=has_content,
    )


def plan(entry: TimetableEntry, existing: list[Lesson]) -> GenerationPlan:
    """Plan generation for the window with the entry's own term."""
    return plan_generation(
        make_term(id=entry.term_id), [entry], existing, start=START, end=END, now=NOW
    )


def test_new_lessons_are_inserted_for_missing_dates() -> None:
    """UF-SYS-05: dates without a lesson get one."""
    entry = monday_entry()

    result = plan(entry, [])

    assert [lesson.origin_date for lesson in result.inserts] == [
        dt.date(2026, 10, 12),
        dt.date(2026, 10, 19),
    ]
    assert all(
        lesson.status == "scheduled" and lesson.audience for lesson in result.inserts
    )


def test_lessons_that_match_are_left_alone() -> None:
    """UF-SYS-05: a second run changes nothing."""
    entry = monday_entry()
    existing = [existing_lesson(entry, dt.date(2026, 10, 12))]

    result = plan(entry, existing)

    assert result.updates == [] and result.cancels == [] and result.deletes == []
    assert [lesson.origin_date for lesson in result.inserts] == [dt.date(2026, 10, 19)]


def test_a_moved_room_updates_future_lessons() -> None:
    """ACA-7: an entry change reaches future lessons."""
    room = new_id()
    entry = monday_entry(room_id=room)
    stored = existing_lesson(entry, dt.date(2026, 10, 12), room=None)

    result = plan(entry, [stored])

    assert result.updates == [stored]
    assert stored.room_id == room


def test_lessons_that_already_started_are_not_updated() -> None:
    """ACA-7: only future lessons follow the timetable."""
    entry = monday_entry(room_id=new_id())
    started = existing_lesson(
        entry, dt.date(2026, 10, 12), starts_at=NOW - dt.timedelta(hours=1)
    )

    assert plan(entry, [started]).updates == []


def test_lessons_changed_by_hand_are_not_overwritten() -> None:
    """ACA-7: is_overridden lessons are left alone."""
    entry = monday_entry(room_id=new_id())
    changed = existing_lesson(entry, dt.date(2026, 10, 12), overridden=True)

    result = plan(entry, [changed])

    assert result.updates == [] and changed.room_id is None


def test_a_lesson_whose_entry_no_longer_produces_it_is_deleted_when_empty() -> None:
    """ACA-7: parity changed to odd, so the lesson on 19.10 (even week) is stale."""
    entry = monday_entry(week_parity="odd")
    stale = existing_lesson(monday_entry(id=entry.id), dt.date(2026, 10, 19))

    result = plan(entry, [stale])

    assert result.deletes == [stale]


def test_a_lesson_with_homework_is_cancelled_instead_of_deleted() -> None:
    """ACA-7: lessons with content are never deleted."""
    entry = monday_entry(week_parity="odd")
    stale = existing_lesson(
        monday_entry(id=entry.id), dt.date(2026, 10, 19), has_content=True
    )

    result = plan(entry, [stale])

    assert result.cancels == [stale] and stale.status == "cancelled"
    assert result.deletes == []


def test_an_overridden_lesson_survives_the_removal_of_its_slot() -> None:
    """ACA-7: hand-changed lessons stay even if the timetable moved on."""
    entry = monday_entry(week_parity="odd")
    kept = existing_lesson(
        monday_entry(id=entry.id), dt.date(2026, 10, 19), overridden=True
    )

    result = plan(entry, [kept])

    assert result.deletes == [] and result.cancels == []


def test_a_cancelled_generated_lesson_comes_back_when_the_entry_produces_it_again() -> (
    None
):
    """ACA-7: cancellation by regeneration is undone if the slot returns."""
    entry = monday_entry()
    lesson = existing_lesson(entry, dt.date(2026, 10, 12), has_content=True)
    lesson.status = "cancelled"

    result = plan(entry, [lesson])

    assert result.updates == [lesson] and lesson.status == "scheduled"


def test_changed_ids_list_every_touched_lesson() -> None:
    """UF-SYS-05: homework due dates are recomputed for all of them."""
    entry = monday_entry(week_parity="odd", room_id=new_id())
    gone = existing_lesson(monday_entry(id=entry.id), dt.date(2026, 10, 19))
    moved = existing_lesson(entry, dt.date(2026, 10, 12))

    result = plan(entry, [gone, moved])

    assert set(result.changed_ids) == {gone.id, moved.id}
