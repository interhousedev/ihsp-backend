"""EMIS curriculum response (``GET student-profiles/curriculum/``).

Only the subject ids and the top-level ``id`` are required. EMIS sends ``""`` for a
missing number, date or code, so those become None; unknown fields are ignored.
"""

from typing import Annotated, Any

from pydantic import AliasChoices, BaseModel, BeforeValidator, Field


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _number(value: Any) -> Any:
    """A whole number; ``""`` is missing and a float is rounded."""
    value = _blank_to_none(value)
    return round(value) if isinstance(value, float) else value


def _text(value: Any) -> Any:
    """A string; ``""`` is missing and a number (a year code) is written out."""
    value = _blank_to_none(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return value


def _flag(value: Any) -> Any:
    """A boolean; ``null`` and ``""`` are False."""
    return False if _blank_to_none(value) is None else value


def _none_to_list(value: Any) -> Any:
    return [] if value is None else value


def _groups(value: Any) -> Any:
    """A list of lists where a ``null`` list is empty."""
    if value is None:
        return []
    if isinstance(value, list):
        return [[] if group is None else group for group in value]
    return value


OptInt = Annotated[int | None, BeforeValidator(_number)]
OptStr = Annotated[str | None, BeforeValidator(_text)]
Flag = Annotated[bool, BeforeValidator(_flag)]


class SubjectNameV1DTO(BaseModel):
    """A name in the three languages (any may be empty)."""

    uz: str | None = None
    ru: str | None = None
    en: str | None = None


class SubjectTypeV1DTO(BaseModel):
    """``edu_subject_type``: 1 general, 2 advanced, 3 vocational, 4 unified."""

    id: OptInt = None
    name: OptStr = None


class EduSubjectV1DTO(BaseModel):
    """The subject itself: names and type."""

    name: SubjectNameV1DTO | None = None
    edu_subject_type: SubjectTypeV1DTO | None = None
    edu_subject_type_id: OptInt = None


class CurriculumItemV1DTO(BaseModel):
    """One line of the curriculum: a subject with its hours over all semesters."""

    edu_subject_id: int
    edu_subject: EduSubjectV1DTO | None = None
    study_hours: OptInt = None


class SemesterSubjectV1DTO(BaseModel):
    """One line of ``semester_edu_subjects``: a subject in one semester."""

    semester_number: OptInt = None
    edu_subject_id: int
    edu_subject: EduSubjectV1DTO | None = None
    is_seperated: Flag = Field(
        default=False, validation_alias=AliasChoices("is_seperated", "is_separated")
    )
    study_hours: OptInt = None
    class_hours: OptInt = None
    independent_work_hours: OptInt = Field(
        default=None,
        validation_alias=AliasChoices("independent_work_hours", "independent_hours"),
    )


class SemesterDatesV1DTO(BaseModel):
    """One of ``semester_dates``: ``DD.MM.YYYY`` strings."""

    start_date: OptStr = None
    end_date: OptStr = None


class DirectionV1DTO(BaseModel):
    """``edu_direction``."""

    id: OptInt = None
    name: OptStr = None
    code: OptStr = None


class YearV1DTO(BaseModel):
    """``start_year`` / ``end_year``: the dates are ``DD.MM.YYYY`` or ISO."""

    code: OptStr = None
    name: OptStr = None
    from_date: OptStr = None
    to_date: OptStr = None


class EduFormV1DTO(BaseModel):
    """``edu_form``."""

    name: OptStr = None


class TemplateV1DTO(BaseModel):
    """``curriculum_template``: only the number of semesters is used."""

    number_of_semesters: OptInt = None


class RatingTypeV1DTO(BaseModel):
    """``rating_type``: the scale of the marks."""

    min_rating: OptInt = None
    max_rating: OptInt = None


class LanguageV1DTO(BaseModel):
    """``edu_language``: the code is "UZ", "RU", ..."""

    code: OptStr = None


class NamedItemV1DTO(BaseModel):
    """An ``exams`` or ``vocational_subjects`` item."""

    id: OptInt = None
    name: SubjectNameV1DTO | None = None
    study_hours: OptInt = None


class CurriculumV1DTO(BaseModel):
    """The ``result`` object of ``GET student-profiles/curriculum/``."""

    id: int
    name: OptStr = None
    edu_direction: DirectionV1DTO | None = None
    speciality: SubjectNameV1DTO | None = None
    edu_form: EduFormV1DTO | None = None
    edu_language: LanguageV1DTO | None = None
    rating_type: RatingTypeV1DTO | None = None
    curriculum_template: TemplateV1DTO | None = None
    start_year: YearV1DTO | None = None
    end_year: YearV1DTO | None = None
    status: OptStr = None
    edu_subject: Annotated[
        list[CurriculumItemV1DTO], BeforeValidator(_none_to_list)
    ] = Field(default_factory=list)
    semester_dates: Annotated[
        list[SemesterDatesV1DTO | None], BeforeValidator(_none_to_list)
    ] = Field(default_factory=list)
    semester_edu_subjects: Annotated[
        list[list[SemesterSubjectV1DTO]], BeforeValidator(_groups)
    ] = Field(default_factory=list)
    exams: Annotated[list[NamedItemV1DTO], BeforeValidator(_none_to_list)] = Field(
        default_factory=list
    )
    vocational_subjects: Annotated[
        list[NamedItemV1DTO], BeforeValidator(_none_to_list)
    ] = Field(default_factory=list)
