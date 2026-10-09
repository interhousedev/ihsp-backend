"""Controls suggested by EMIS lessons: planned inside a control week, else tentative."""

import datetime as dt

from app.modules.academic.domain.assessments.suggestions import (
    promote_inside_weeks,
    suggestions_from_lessons,
)
from tests.academic.assessments.factories import (
    MATH,
    OTHER_GROUP,
    PHYSICS,
    make_assessment,
    make_lesson,
    make_term,
    standard_term,
)

D = dt.date.fromisoformat


def test_a_control_lesson_inside_a_week_is_planned() -> None:
    """EMIS control weeks are right: the suggestion needs no confirmation."""
    lesson = make_lesson(date=D("2026-10-21"), topic="  Algebra review  ", room="204")

    (new,) = suggestions_from_lessons([lesson], [], [standard_term()])

    assert (new.status, new.source, new.control) == ("planned", "emis", "midterm_1")
    assert (new.title, new.room, new.lesson_id) == (
        "Algebra review",
        "204",
        lesson.lesson_id,
    )
    assert new.starts_at == lesson.starts_at
    assert new.created_by is None


def test_a_control_lesson_outside_every_week_is_tentative() -> None:
    """EMIS only hints; a teacher or Administration confirms it."""
    lesson = make_lesson(date=D("2026-11-10"))

    (new,) = suggestions_from_lessons([lesson], [], [standard_term()])

    assert (new.status, new.control) == ("tentative", None)


def test_without_any_week_every_suggestion_is_tentative() -> None:
    """Administration has not set the weeks of the term yet."""
    (new,) = suggestions_from_lessons([make_lesson()], [], [make_term()])

    assert new.status == "tentative"


def test_a_final_lesson_is_matched_against_the_final_week_only() -> None:
    """A final in a midterm week is outside the final week."""
    final = make_lesson(kind="final", date=D("2026-10-21"))
    in_final_week = make_lesson(kind="final", date=D("2026-12-15"), subject_id=PHYSICS)

    first, second = suggestions_from_lessons(
        [final, in_final_week], [], [standard_term()]
    )

    assert (first.status, first.control) == ("tentative", None)
    assert (second.status, second.control) == ("planned", "final")


def test_a_double_period_gives_one_control() -> None:
    """Two lessons the same day for the same subject and group are one control."""
    one = make_lesson(date=D("2026-10-21"))
    two = make_lesson(date=D("2026-10-21"))

    assert len(suggestions_from_lessons([one, two], [], [standard_term()])) == 1


def test_different_subjects_and_groups_each_get_their_own() -> None:
    """The duplicate rule is per subject and audience."""
    lessons = [
        make_lesson(subject_id=MATH),
        make_lesson(subject_id=PHYSICS),
        make_lesson(audience=(str(OTHER_GROUP),)),
    ]

    assert len(suggestions_from_lessons(lessons, [], [standard_term()])) == 3


def test_a_lesson_that_already_has_a_control_gives_nothing() -> None:
    """The generator is safe to run again: the link to the lesson is the key."""
    lesson = make_lesson(date=D("2026-10-21"))
    stored = make_assessment(
        lesson_id=lesson.lesson_id, source="emis", status="planned"
    )

    assert suggestions_from_lessons([lesson], [stored], [standard_term()]) == []


def test_a_teacher_control_for_the_same_week_blocks_the_suggestion() -> None:
    """No second midterm 1 for the same subject because EMIS lists one too."""
    taught = make_assessment(date=D("2026-10-22"), control="midterm_1")

    got = suggestions_from_lessons(
        [make_lesson(date=D("2026-10-21"))], [taught], [standard_term()]
    )

    assert got == []


def test_a_dismissed_suggestion_stays_dismissed() -> None:
    """The cancelled row remains, so the lesson is not suggested again."""
    gone = make_assessment(
        status="cancelled", source="emis", date=D("2026-10-21"), lesson_id=None
    )

    got = suggestions_from_lessons(
        [make_lesson(date=D("2026-10-21"))], [gone], [standard_term()]
    )

    assert got == []


def test_suggestions_are_listed_by_date() -> None:
    """Deterministic order: earliest first."""
    later = make_lesson(date=D("2026-12-15"), kind="final")
    earlier = make_lesson(date=D("2026-10-21"))

    got = suggestions_from_lessons([later, earlier], [], [standard_term()])

    assert [n.date for n in got] == [D("2026-10-21"), D("2026-12-15")]


def test_a_tentative_suggestion_becomes_planned_when_a_week_covers_it() -> None:
    """Administration sets the weeks after EMIS lessons were first read."""
    inside = make_assessment(
        status="tentative", source="emis", date=D("2026-10-21"), kind="midterm"
    )
    outside = make_assessment(status="tentative", source="emis", date=D("2026-11-10"))

    (promoted,) = promote_inside_weeks([inside, outside], [standard_term()])

    assert promoted.id == inside.id
    assert (promoted.status, promoted.control) == ("planned", "midterm_1")


def test_only_tentative_emis_suggestions_are_promoted() -> None:
    """A head student's guess, teacher controls and dismissed ones stay as they are."""
    day = D("2026-10-21")
    others = [
        make_assessment(status="tentative", source="head_student", date=day),
        make_assessment(status="planned", source="emis", date=day),
        make_assessment(status="cancelled", source="emis", date=day),
        make_assessment(status="planned", source="teacher", date=day),
    ]

    assert promote_inside_weeks(others, [standard_term()]) == []
