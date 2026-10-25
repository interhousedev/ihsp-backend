"""Semester dates, subject names and the term of a semester (pure functions)."""

import datetime as dt

from app.modules.academic.domain.curriculum.names import (
    display_name,
    fill_missing_names,
    first_names,
)
from app.modules.academic.domain.curriculum.records import (
    curriculum_from_emis,
    semester_subjects_from_emis,
)
from app.modules.academic.domain.curriculum.semesters import (
    current_semester,
    term_for_semester,
)
from app.shared.contracts.emis import EmisName, EmisSemesterDates
from app.shared.ids import new_id
from tests.academic.schedule.curriculum_builders import (
    ENGLISH,
    MATH,
    SEMESTERS,
    make_curriculum,
    semester_subject,
)

D = dt.date.fromisoformat

# - - - current_semester - - -


def test_the_semester_that_holds_today_is_current() -> None:
    """Inside a semester, the ends included."""
    assert current_semester(SEMESTERS, D("2026-10-06")) == 3
    assert current_semester(SEMESTERS, D("2026-09-01")) == 3
    assert current_semester(SEMESTERS, D("2026-12-26")) == 3


def test_between_two_semesters_the_one_that_ended_last_is_current() -> None:
    """Winter break: the autumn semester is still the latest that started."""
    assert current_semester(SEMESTERS, D("2026-12-31")) == 3
    assert current_semester(SEMESTERS, D("2026-07-01")) == 2


def test_before_the_first_semester_there_is_none() -> None:
    """Nothing has started yet."""
    assert current_semester(SEMESTERS, D("2025-08-31")) is None


def test_after_the_last_semester_the_last_one_stays_current() -> None:
    """A graduated group keeps its last semester."""
    assert current_semester(SEMESTERS, D("2028-01-01")) == 4


def test_without_semester_dates_there_is_no_current_semester() -> None:
    """An empty list gives none."""
    assert current_semester([], D("2026-10-06")) is None


def test_the_input_order_does_not_matter() -> None:
    """Semesters are looked at by date, not by position."""
    shuffled = [SEMESTERS[2], SEMESTERS[0], SEMESTERS[3], SEMESTERS[1]]

    assert current_semester(shuffled, D("2026-02-01")) == 2


def test_overlapping_semesters_prefer_the_one_that_started_last() -> None:
    """Two semesters that both hold today: the later start wins."""
    overlapping = [
        EmisSemesterDates(1, D("2026-01-01"), D("2026-06-30")),
        EmisSemesterDates(2, D("2026-05-01"), D("2026-08-31")),
    ]

    assert current_semester(overlapping, D("2026-05-15")) == 2


# - - - fill_missing_names - - -


def test_empty_languages_are_filled_from_the_offer() -> None:
    """uz and en are empty; ru is given."""
    filled = fill_missing_names(
        {"uz": "", "ru": "Математика", "en": ""},
        EmisName(uz="Matematika", ru="Матем.", en="Mathematics"),
    )

    assert filled == {"uz": "Matematika", "ru": "Математика", "en": "Mathematics"}


def test_a_name_that_exists_is_never_overwritten() -> None:
    """The offer differs in every language and changes nothing."""
    current = {"uz": "Algebra", "ru": "Алгебра", "en": "Algebra"}

    filled = fill_missing_names(current, EmisName("Matematika", "Математика", "Maths"))

    assert filled == current


def test_blank_names_count_as_empty_on_both_sides() -> None:
    """Whitespace in the current name is empty; a blank offer fills nothing."""
    filled = fill_missing_names(
        {"uz": "   ", "ru": "", "en": "Physics"},
        EmisName(uz="  Fizika  ", ru="   ", en="Phys"),
    )

    assert filled == {"uz": "Fizika", "ru": "", "en": "Physics"}


def test_a_missing_language_is_filled_and_the_input_is_not_changed() -> None:
    """A dict without the key is as empty as a blank value; the result is new."""
    current = {"ru": "Физика"}

    filled = fill_missing_names(current, EmisName(uz="Fizika", en="Physics"))

    assert filled == {"ru": "Физика", "uz": "Fizika", "en": "Physics"}
    assert current == {"ru": "Физика"}


def test_several_offers_of_one_subject_merge_per_language() -> None:
    """The first non-blank name of each language wins."""
    merged = first_names(
        [EmisName(uz="Fizika"), EmisName(uz="Fizika 2", ru="Физика"), EmisName()]
    )

    assert merged == EmisName(uz="Fizika", ru="Физика", en="")


def test_the_display_name_prefers_ru_then_uz_then_en() -> None:
    """The order used to sort subjects."""
    assert display_name({"uz": "A", "ru": "B", "en": "C"}) == "B"
    assert display_name({"uz": "A", "ru": " ", "en": "C"}) == "A"
    assert display_name({"uz": "", "ru": "", "en": "C"}) == "C"
    assert display_name({}) == ""


# - - - term_for_semester - - -


def test_an_autumn_semester_is_the_first_half_of_its_year() -> None:
    """September 2026 starts the year 2026-2027."""
    term = term_for_semester(D("2026-09-01"), D("2026-12-26"), 3)

    assert (term.number, term.academic_year, term.half) == (3, "2026-2027", 1)
    assert (term.starts_on, term.ends_on) == (D("2026-09-01"), D("2026-12-26"))


def test_a_spring_semester_is_the_second_half_of_the_year_before() -> None:
    """January 2027 belongs to 2026-2027."""
    term = term_for_semester(D("2027-01-11"), D("2027-05-29"), 4)

    assert (term.academic_year, term.half) == ("2026-2027", 2)


def test_august_already_starts_the_next_year() -> None:
    """The boundary: August is autumn, July is spring."""
    assert term_for_semester(D("2026-08-25"), D("2026-12-26"), 1).half == 1
    assert term_for_semester(D("2026-07-25"), D("2026-12-26"), 1).half == 2


# - - - records - - -


def test_the_curriculum_is_mapped_with_names_as_emis_sent_them() -> None:
    """Empty languages stay "", dates are sorted by number."""
    group_id = new_id()
    now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
    reversed_dates = tuple(reversed(SEMESTERS))

    header = curriculum_from_emis(
        group_id, make_curriculum(semesters=reversed_dates), now
    )

    assert [span.number for span in header.semester_dates] == [1, 2, 3, 4]
    assert header.speciality == {
        "uz": "Tabiiy fanlar",
        "ru": "Естественные науки",
        "en": "",
    }
    assert header.subject_totals[2].name == {
        "uz": "Ingliz tili",
        "ru": "",
        "en": "English",
    }
    assert header.direction is not None and header.direction.code == "3010100"
    assert (header.rating_min, header.rating_max) == (0, 100)
    assert (
        header.exams[0].study_hours == 12 and header.vocational[0].study_hours is None
    )
    assert header.fetched_at == now


def test_a_subject_listed_twice_in_a_semester_is_kept_once() -> None:
    """The primary key is (semester, subject)."""
    first = semester_subject(3, MATH, EmisName(uz="Matematika"), hours=68)
    second = semester_subject(3, MATH, EmisName(uz="Matematika 2"), hours=34)
    other = semester_subject(2, ENGLISH, EmisName(en="English"))

    rows = semester_subjects_from_emis([first, second, other])

    assert [(r.semester_number, r.emis_subject_id) for r in rows] == [
        (2, ENGLISH),
        (3, MATH),
    ]
    assert rows[1].study_hours == 68
