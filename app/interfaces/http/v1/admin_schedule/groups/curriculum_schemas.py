"""Response schemas of the group curriculum routes (admin and student)."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import ApiModel


class CurriculumNameResponse(ApiModel):
    """A name in the three languages; a language EMIS left empty is ``""``."""

    uz: str
    ru: str
    en: str


class CurriculumDirectionResponse(ApiModel):
    """The education direction."""

    emis_id: int | None
    name: str | None
    code: str | None


class CurriculumRatingScaleResponse(ApiModel):
    """The rating scale of the curriculum."""

    min: int | None
    max: int | None


class CurriculumSubjectResponse(ApiModel):
    """A subject of a semester; ``subject_id`` is null while no subject row exists."""

    subject_id: UUID | None
    emis_subject_id: int
    name: CurriculumNameResponse
    subject_type_id: int | None
    study_hours: int | None
    class_hours: int | None
    independent_hours: int | None
    is_separated: bool


class CurriculumSemesterResponse(ApiModel):
    """A semester with its dates (null when only the subjects mention it)."""

    number: int
    starts_on: dt.date | None
    ends_on: dt.date | None
    is_current: bool
    subjects: list[CurriculumSubjectResponse]


class CurriculumExtraResponse(ApiModel):
    """An exam or a vocational subject."""

    name: CurriculumNameResponse
    study_hours: int | None


class CurriculumResponse(ApiModel):
    """The EMIS curriculum of a group."""

    emis_curriculum_id: int
    name: str
    speciality: CurriculumNameResponse | None
    direction: CurriculumDirectionResponse | None
    edu_form: str | None
    language_code: str | None
    rating_scale: CurriculumRatingScaleResponse | None
    current_semester: int | None
    fetched_at: dt.datetime
    semesters: list[CurriculumSemesterResponse]
    exams: list[CurriculumExtraResponse]
    vocational_subjects: list[CurriculumExtraResponse]


class CurriculumSyncResponse(ApiModel):
    """The result of POST /v1/admin/groups/{id}/curriculum/sync."""

    status: Literal["synced", "no_student"]
    curriculum: CurriculumResponse | None
