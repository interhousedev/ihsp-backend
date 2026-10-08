"""EMIS curriculum response."""

from pydantic import BaseModel, Field


class SubjectNameV1DTO(BaseModel):
    """A subject name in the three languages (any may be empty)."""

    uz: str | None = None
    ru: str | None = None
    en: str | None = None


class EduSubjectV1DTO(BaseModel):
    """The subject itself."""

    name: SubjectNameV1DTO = Field(default_factory=SubjectNameV1DTO)


class CurriculumItemV1DTO(BaseModel):
    """One line of the curriculum."""

    edu_subject_id: int
    edu_subject: EduSubjectV1DTO = Field(default_factory=EduSubjectV1DTO)


class CurriculumV1DTO(BaseModel):
    """The ``result`` object of ``GET student-profiles/curriculum/``."""

    edu_subject: list[CurriculumItemV1DTO] = Field(default_factory=list)
