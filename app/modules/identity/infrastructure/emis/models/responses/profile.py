"""EMIS student profile response (only the fields IHSP keeps)."""

from pydantic import BaseModel


class CitizenV1DTO(BaseModel):
    """Name part of the citizen record; birth date and gender are never read."""

    first_name: str
    last_name: str
    middle_name: str | None = None


class EduGroupV1DTO(BaseModel):
    """The student's study group."""

    name: str
    curriculum_id: int | None = None
    current_semester: int | None = None


class ProfileV1DTO(BaseModel):
    """The ``result`` object of the profile endpoint."""

    id: int
    citizen: CitizenV1DTO
    institution_id: int
    edu_group_id: int
    edu_group: EduGroupV1DTO
