"""SYNC-3: the curriculum DTO reads the whole EMIS response and tolerates its gaps."""

from typing import Any

from app.modules.identity.infrastructure.emis.fake import fake_curriculum_result
from app.modules.identity.infrastructure.emis.models.responses.curriculum import (
    CurriculumV1DTO,
)

import pytest
from pydantic import ValidationError


def parse(result: dict[str, Any]) -> CurriculumV1DTO:
    return CurriculumV1DTO.model_validate(result)


def test_the_full_sample_response_is_read() -> None:
    """SYNC-3: every part of the real response lands in the DTO."""
    dto = parse(fake_curriculum_result())

    assert (dto.id, dto.name) == (2124, "ТН, МТН, БТН 2025-2027")
    assert dto.edu_direction is not None and dto.edu_direction.code == "3010100"
    assert dto.start_year is not None and dto.start_year.from_date == "01.09.2025"
    assert dto.end_year is not None and dto.end_year.name == "2026-2027"
    assert dto.edu_form is not None and dto.edu_form.name == "Kunduzgi"
    assert dto.curriculum_template is not None
    assert dto.curriculum_template.number_of_semesters == 4
    assert [i.edu_subject_id for i in dto.edu_subject] == list(range(101, 109))
    first_semester = dto.semester_dates[0]
    assert first_semester is not None
    assert (first_semester.start_date, first_semester.end_date) == (
        "03.09.2025",
        "20.01.2026",
    )
    assert len(dto.semester_dates) == 4
    assert [len(group) for group in dto.semester_edu_subjects] == [8, 8, 8, 8]
    assert dto.rating_type is not None
    assert (dto.rating_type.min_rating, dto.rating_type.max_rating) == (3, 5)
    assert dto.edu_language is not None and dto.edu_language.code == "RU"
    assert len(dto.exams) == 3 and len(dto.vocational_subjects) == 2
    assert dto.status == "APPROVED"
    assert dto.speciality is not None and dto.speciality.en == "Technology track"


def test_empty_names_stay_empty_strings() -> None:
    """SYNC-3: EMIS sends "" for a language it has no name in."""
    dto = parse(fake_curriculum_result())

    uzbek = next(i for i in dto.edu_subject if i.edu_subject_id == 105)
    assert uzbek.edu_subject is not None and uzbek.edu_subject.name is not None
    assert (uzbek.edu_subject.name.ru, uzbek.edu_subject.name.en) == ("", "")


def test_the_subject_type_is_read_from_the_subject() -> None:
    """SYNC-3: subject types 1 to 4 sit in edu_subject.edu_subject_type."""
    dto = parse(fake_curriculum_result())

    types = {
        i.edu_subject.edu_subject_type.id
        for i in dto.edu_subject
        if i.edu_subject and i.edu_subject.edu_subject_type
    }
    assert types == {1, 2, 3, 4}


def test_empty_strings_are_missing_numbers_and_dates() -> None:
    """SYNC-3: "" in a number or date field means None, not a validation error."""
    dto = parse(
        {
            "id": 1,
            "name": " ",
            "status": "",
            "edu_subject": [{"edu_subject_id": 5, "study_hours": ""}],
            "semester_dates": [{"start_date": "", "end_date": " "}],
            "rating_type": {"min_rating": "", "max_rating": ""},
            "curriculum_template": {"number_of_semesters": ""},
            "start_year": {"code": "", "from_date": "", "to_date": ""},
            "semester_edu_subjects": [
                [
                    {
                        "semester_number": "",
                        "edu_subject_id": 5,
                        "study_hours": "",
                        "class_hours": "",
                        "independent_work_hours": "",
                    }
                ]
            ],
            "exams": [{"id": "", "study_hours": ""}],
        }
    )

    assert (dto.name, dto.status) == (None, None)
    assert dto.edu_subject[0].study_hours is None
    assert (dto.semester_dates[0] or pytest.fail()).start_date is None
    assert dto.rating_type is not None and dto.rating_type.min_rating is None
    assert dto.curriculum_template is not None
    assert dto.curriculum_template.number_of_semesters is None
    assert dto.start_year is not None and dto.start_year.from_date is None
    row = dto.semester_edu_subjects[0][0]
    assert (row.semester_number, row.study_hours, row.class_hours) == (None, None, None)
    assert row.independent_work_hours is None
    assert (dto.exams[0].id, dto.exams[0].study_hours) == (None, None)


@pytest.mark.parametrize("key", ["is_seperated", "is_separated"])
def test_both_spellings_of_the_separated_flag_are_read(key: str) -> None:
    """SYNC-3: EMIS spells it "is_seperated"; the correct spelling works as well."""
    dto = parse(
        {
            "id": 1,
            "semester_edu_subjects": [[{"edu_subject_id": 5, key: True}]],
        }
    )

    assert dto.semester_edu_subjects[0][0].is_seperated is True


@pytest.mark.parametrize("value", [None, "", False])
def test_a_missing_separated_flag_is_false(value: object) -> None:
    """SYNC-3: null, "" and an absent flag all mean "not separated"."""
    with_value = parse(
        {
            "id": 1,
            "semester_edu_subjects": [
                [{"edu_subject_id": 5, "is_seperated": value}],
                [{"edu_subject_id": 5}],
            ],
        }
    )

    assert [group[0].is_seperated for group in with_value.semester_edu_subjects] == [
        False,
        False,
    ]


def test_unknown_fields_are_ignored_at_every_level() -> None:
    """SYNC-3: EMIS may add fields; they never break the parse."""
    result = fake_curriculum_result()
    result["brand_new"] = {"x": 1}
    result["edu_subject"][0]["extra"] = [1, 2]
    result["edu_subject"][0]["edu_subject"]["can_be_divided"] = True
    result["semester_dates"][0]["note"] = "x"
    result["semester_edu_subjects"][0][0]["room"] = 4
    result["rating_type"]["description"] = "scale"
    result["exams"][0]["kind"] = "final"

    dto = parse(result)

    assert dto.id == 2124 and len(dto.edu_subject) == 8


def test_only_the_ids_are_required() -> None:
    """SYNC-3: a bare curriculum with an id is valid, and so are bare subjects."""
    bare = parse({"id": 9})
    one = parse({"id": 9, "edu_subject": [{"edu_subject_id": 3}]})

    assert bare.edu_subject == [] and bare.semester_dates == []
    assert bare.semester_edu_subjects == [] and bare.exams == []
    assert bare.vocational_subjects == [] and bare.edu_direction is None
    assert bare.rating_type is None and bare.speciality is None
    assert one.edu_subject[0].edu_subject is None
    assert one.edu_subject[0].study_hours is None


def test_null_lists_and_objects_are_empty_or_missing() -> None:
    """SYNC-3: null for a list is an empty list, null for an object is None."""
    dto = parse(
        {
            "id": 9,
            "edu_subject": None,
            "semester_dates": None,
            "semester_edu_subjects": [None, [{"edu_subject_id": 3}]],
            "exams": None,
            "vocational_subjects": None,
            "edu_direction": None,
            "speciality": None,
            "rating_type": None,
        }
    )

    assert dto.edu_subject == [] and dto.semester_dates == []
    assert [len(group) for group in dto.semester_edu_subjects] == [0, 1]
    assert dto.exams == [] and dto.vocational_subjects == []
    assert dto.edu_direction is None and dto.speciality is None


def test_numbers_may_arrive_as_floats_or_digits() -> None:
    """SYNC-3: 72.0 hours, "3" and a numeric year code are all accepted."""
    dto = parse(
        {
            "id": "2124",
            "edu_subject": [{"edu_subject_id": "5", "study_hours": 72.0}],
            "rating_type": {"min_rating": "3", "max_rating": 5.0},
            "start_year": {"code": 2025},
        }
    )

    assert dto.id == 2124
    assert (dto.edu_subject[0].edu_subject_id, dto.edu_subject[0].study_hours) == (
        5,
        72,
    )
    assert dto.rating_type is not None and dto.rating_type.max_rating == 5
    assert dto.start_year is not None and dto.start_year.code == "2025"


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"id": None},
        {"id": 1, "edu_subject": [{"study_hours": 5}]},
        {"id": 1, "semester_edu_subjects": [[{"semester_number": 1}]]},
        {"id": 1, "edu_subject": "not a list"},
    ],
)
def test_a_response_without_the_ids_is_rejected(result: dict[str, Any]) -> None:
    """SYNC-3: no curriculum id or no subject id means EMIS changed."""
    with pytest.raises(ValidationError):
        parse(result)
