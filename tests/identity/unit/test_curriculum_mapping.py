"""SYNC-3: the curriculum DTO becomes the EmisCurriculum contract."""

from datetime import date
from typing import Any

from app.modules.identity.infrastructure.emis.fake import fake_curriculum_result
from app.modules.identity.infrastructure.emis.mapping import (
    curriculum_subjects,
    to_curriculum,
    to_subjects,
)
from app.modules.identity.infrastructure.emis.models.responses.curriculum import (
    CurriculumV1DTO,
)
from app.shared.contracts.emis import (
    EmisCurriculum,
    EmisDirection,
    EmisName,
    EmisSubject,
    EmisYear,
)
from tests.identity.emis.emis_fixtures import load_fixture

import pytest
from structlog.testing import capture_logs


def curriculum_of(result: dict[str, Any]) -> EmisCurriculum:
    return to_curriculum(CurriculumV1DTO.model_validate(result))


@pytest.fixture
def sample() -> EmisCurriculum:
    return curriculum_of(fake_curriculum_result())


def test_the_header_of_the_sample_is_mapped(sample: EmisCurriculum) -> None:
    """SYNC-3: id, name, direction, speciality, form, language, scale, status."""
    assert (sample.emis_id, sample.name) == (2124, "ТН, МТН, БТН 2025-2027")
    assert sample.direction == EmisDirection(312, "Umumiy o'rta ta'lim", "3010100")
    assert sample.speciality == EmisName(
        "Texnologik yo'nalish", "Технологическое направление", "Technology track"
    )
    assert sample.edu_form == "Kunduzgi"
    assert sample.language_code == "RU"
    assert (sample.rating_min, sample.rating_max) == (3, 5)
    assert sample.semesters_count == 4
    assert sample.status == "APPROVED"


def test_the_academic_years_are_dates(sample: EmisCurriculum) -> None:
    """SYNC-3: start_year and end_year carry code, name and real dates."""
    assert sample.start_year == EmisYear(
        "2025", "2025-2026", date(2025, 9, 1), date(2026, 8, 31)
    )
    assert sample.end_year == EmisYear(
        "2026", "2026-2027", date(2026, 9, 1), date(2027, 8, 31)
    )


def test_the_semesters_are_numbered_from_one_with_their_dates(
    sample: EmisCurriculum,
) -> None:
    """SYNC-3: DD.MM.YYYY dates of semester_dates become dates by position."""
    assert [(s.number, s.starts_on, s.ends_on) for s in sample.semesters] == [
        (1, date(2025, 9, 3), date(2026, 1, 20)),
        (2, date(2026, 1, 26), date(2026, 5, 29)),
        (3, date(2026, 9, 2), date(2027, 1, 22)),
        (4, date(2027, 2, 1), date(2027, 5, 28)),
    ]


def test_the_subjects_carry_names_types_and_total_hours(
    sample: EmisCurriculum,
) -> None:
    """SYNC-3: edu_subject becomes the totals over the whole curriculum."""
    by_id = {s.emis_subject_id: s for s in sample.subjects}

    assert list(by_id) == list(range(101, 109))
    assert by_id[101].name == EmisName("Matematika", "Математика", "Mathematics")
    assert (by_id[101].subject_type_id, by_id[101].study_hours) == (2, 340)
    assert {s.subject_type_id for s in sample.subjects} == {1, 2, 3, 4}
    assert by_id[107].subject_type_id == 3


def test_empty_names_stay_empty_strings_without_a_fallback(
    sample: EmisCurriculum,
) -> None:
    """SYNC-3: the contract keeps what EMIS sent; fallbacks are the reader's job."""
    by_id = {s.emis_subject_id: s for s in sample.subjects}

    assert by_id[105].name == EmisName("O'zbek tili", "", "")
    assert by_id[108].name == EmisName("Kimyo", "Химия", "")


def test_the_semester_subjects_are_listed_semester_by_semester(
    sample: EmisCurriculum,
) -> None:
    """SYNC-3: every semester has its own hours; the numbers come from the items."""
    assert [s.semester_number for s in sample.semester_subjects] == [
        n for n in (1, 2, 3, 4) for _ in range(8)
    ]
    third = [s for s in sample.semester_subjects if s.semester_number == 3]
    assert [s.emis_subject_id for s in third] == list(range(101, 109))
    math, physics = third[0], third[1]
    assert (math.study_hours, math.class_hours, math.independent_hours) == (85, 68, 17)
    assert (physics.study_hours, physics.class_hours) == (68, 51)
    assert math.name == EmisName("Matematika", "Математика", "Mathematics")
    assert math.subject_type_id == 2


def test_the_separated_flag_follows_is_seperated(sample: EmisCurriculum) -> None:
    """SYNC-3: English and Informatics are taught in halves; null hours stay None."""
    first = [s for s in sample.semester_subjects if s.semester_number == 1]

    assert {s.emis_subject_id for s in first if s.is_separated} == {103, 107}
    russian = next(s for s in first if s.emis_subject_id == 104)
    assert russian.independent_hours is None
    assert next(s for s in first if s.emis_subject_id == 105).independent_hours == 0


def test_hours_of_the_semesters_add_up_to_the_totals(sample: EmisCurriculum) -> None:
    """SYNC-3: the sample is consistent: per-semester study hours sum to the total."""
    for subject in sample.subjects:
        parts = [
            s.study_hours or 0
            for s in sample.semester_subjects
            if s.emis_subject_id == subject.emis_subject_id
        ]
        assert sum(parts) == subject.study_hours


def test_exams_and_vocational_subjects_are_mapped(sample: EmisCurriculum) -> None:
    """SYNC-3: both lists keep ids, names in three languages and hours."""
    assert [(e.emis_id, e.name.uz, e.study_hours) for e in sample.exams] == [
        (1, "Yakuniy imtihon", 24),
        (2, "Oraliq imtihon", 16),
        (3, "Bitiruv malakaviy ishi", 48),
    ]
    assert sample.exams[1].name == EmisName(
        "Oraliq imtihon", "Промежуточный экзамен", ""
    )
    assert [v.emis_id for v in sample.vocational_subjects] == [7001, 7002]
    assert sample.vocational_subjects[1].name.ru == ""


def test_a_bare_curriculum_maps_to_empty_parts() -> None:
    """SYNC-3: only the id is required; everything else is None or empty."""
    bare = curriculum_of({"id": 9})

    assert bare == EmisCurriculum(
        emis_id=9,
        name="",
        direction=None,
        speciality=None,
        edu_form=None,
        language_code=None,
        rating_min=None,
        rating_max=None,
        start_year=None,
        end_year=None,
        semesters_count=None,
        status=None,
        semesters=(),
        subjects=(),
        semester_subjects=(),
        exams=(),
        vocational_subjects=(),
    )


def test_blank_parts_become_none_instead_of_empty_objects() -> None:
    """SYNC-3: a direction, speciality or year with nothing in it is None."""
    curriculum = curriculum_of(
        {
            "id": 9,
            "edu_direction": {"id": "", "name": " ", "code": ""},
            "speciality": {"uz": "", "ru": "", "en": ""},
            "start_year": {"code": "", "name": "", "from_date": "", "to_date": ""},
            "end_year": {"from_date": "not a date"},
            "edu_form": {"name": ""},
            "edu_language": {"code": ""},
            "status": "  ",
        }
    )

    assert curriculum.direction is None and curriculum.speciality is None
    assert curriculum.start_year is None and curriculum.end_year is None
    assert curriculum.edu_form is None and curriculum.language_code is None
    assert curriculum.status is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("01.09.2025", date(2025, 9, 1)),
        ("2025-09-01", date(2025, 9, 1)),
        ("2025-09-01T00:00:00", date(2025, 9, 1)),
        (" 31.08.2026 ", date(2026, 8, 31)),
        ("31/08/2026", None),
        ("32.13.2026", None),
        ("", None),
    ],
)
def test_year_dates_are_dd_mm_yyyy_or_iso_else_none(
    text: str, expected: date | None
) -> None:
    """SYNC-3: an unreadable academic-year date is None and never an error."""
    curriculum = curriculum_of(
        {"id": 9, "start_year": {"code": "2025", "from_date": text}}
    )

    assert curriculum.start_year is not None
    assert curriculum.start_year.from_date == expected


def test_a_semester_with_unreadable_dates_is_skipped_with_a_warning() -> None:
    """SYNC-3: the others keep their place in the numbering; nothing raises."""
    with capture_logs() as logs:
        curriculum = curriculum_of(
            {
                "id": 9,
                "semester_dates": [
                    {"start_date": "soon", "end_date": "20.01.2026"},
                    {"start_date": "26.01.2026", "end_date": "29.05.2026"},
                    {"start_date": "", "end_date": ""},
                    None,
                    {"start_date": "01.02.2027", "end_date": "01.01.2027"},
                    {"start_date": "02.09.2027", "end_date": "2028-01-22"},
                ],
            }
        )

    assert [(s.number, s.starts_on, s.ends_on) for s in curriculum.semesters] == [
        (2, date(2026, 1, 26), date(2026, 5, 29)),
        (6, date(2027, 9, 2), date(2028, 1, 22)),
    ]
    skipped = [log for log in logs if log["event"] == "emis_semester_dates_skipped"]
    assert [log["semester"] for log in skipped] == [1, 3, 4, 5]
    assert all(log["log_level"] == "warning" for log in skipped)


def test_the_semester_number_comes_from_the_item_else_from_the_position() -> None:
    """SYNC-3: a missing or blank semester_number is the 1-based list position."""
    curriculum = curriculum_of(
        {
            "id": 9,
            "semester_edu_subjects": [
                [{"edu_subject_id": 1}, {"semester_number": "", "edu_subject_id": 2}],
                [{"semester_number": 5, "edu_subject_id": 3}],
                [],
                [{"edu_subject_id": 4, "is_separated": True}],
            ],
        }
    )

    assert [
        (s.semester_number, s.emis_subject_id, s.is_separated)
        for s in (curriculum.semester_subjects)
    ] == [(1, 1, False), (1, 2, False), (5, 3, False), (4, 4, True)]
    assert curriculum.semester_subjects[0].name == EmisName()
    assert curriculum.semester_subjects[0].subject_type_id is None


def test_the_subject_type_may_sit_beside_the_subject() -> None:
    """SYNC-3: edu_subject_type_id is read when edu_subject_type is missing."""
    curriculum = curriculum_of(
        {
            "id": 9,
            "edu_subject": [
                {"edu_subject_id": 1, "edu_subject": {"edu_subject_type_id": 3}},
                {"edu_subject_id": 2, "edu_subject": {"edu_subject_type": {"id": 4}}},
            ],
        }
    )

    assert [s.subject_type_id for s in curriculum.subjects] == [3, 4]


def test_to_subjects_applies_the_name_fallback_to_the_recorded_fixture() -> None:
    """SYNC-3: unchanged: an empty name is the first non-empty of uz, ru, en."""
    dto = CurriculumV1DTO.model_validate(load_fixture("curriculum.json")["result"])

    subjects = to_subjects(dto)

    assert subjects == [
        EmisSubject(35, "Geometriya", "Geometriya", "Geometry"),
        EmisSubject(19, "Ingliz tili", "Английский язык", "English"),
    ]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ({"uz": "Fizika", "ru": "", "en": ""}, ("Fizika", "Fizika", "Fizika")),
        ({"uz": "", "ru": "Физика", "en": ""}, ("Физика", "Физика", "Физика")),
        ({"uz": " ", "ru": "", "en": "Physics"}, ("Physics", "Physics", "Physics")),
        (
            {"uz": " Fizika ", "ru": None, "en": "Physics"},
            ("Fizika", "Fizika", "Physics"),
        ),
        ({"uz": "", "ru": "", "en": ""}, ("Subject 7", "Subject 7", "Subject 7")),
        (None, ("Subject 7", "Subject 7", "Subject 7")),
    ],
)
def test_to_subjects_fills_a_missing_name_from_another_language(
    name: dict[str, str | None] | None, expected: tuple[str, str, str]
) -> None:
    """SYNC-3: uz, else ru, else en, else "Subject <id>"; names are stripped."""
    item: dict[str, Any] = {"edu_subject_id": 7}
    if name is not None:
        item["edu_subject"] = {"name": name}
    dto = CurriculumV1DTO.model_validate({"id": 1, "edu_subject": [item]})

    (subject,) = to_subjects(dto)

    assert (subject.name_uz, subject.name_ru, subject.name_en) == expected


def test_the_subjects_of_the_sample_come_from_the_same_curriculum(
    sample: EmisCurriculum,
) -> None:
    """SYNC-3: to_subjects is the fallback view of to_curriculum(...).subjects."""
    dto = CurriculumV1DTO.model_validate(fake_curriculum_result())

    assert to_subjects(dto) == curriculum_subjects(sample)
    uzbek = next(s for s in curriculum_subjects(sample) if s.emis_subject_id == 105)
    assert (uzbek.name_uz, uzbek.name_ru, uzbek.name_en) == (
        "O'zbek tili",
        "O'zbek tili",
        "O'zbek tili",
    )
