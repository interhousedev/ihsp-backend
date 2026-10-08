"""JSON shapes of the internal EMIS gateway (the contract dataclasses as JSON)."""

from datetime import date

from app.shared.contracts.emis import (
    EmisMarkType,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
)

from pydantic import BaseModel


class EmisProfileResponse(BaseModel):
    """EmisProfile."""

    emis_student_id: int
    first_name: str
    last_name: str
    middle_name: str | None
    institution_id: int
    group_emis_id: int
    group_name: str
    current_semester: int | None
    curriculum_id: int | None

    @classmethod
    def from_contract(cls, profile: EmisProfile) -> "EmisProfileResponse":
        """Build the response from the contract dataclass."""
        return cls(
            emis_student_id=profile.emis_student_id,
            first_name=profile.first_name,
            last_name=profile.last_name,
            middle_name=profile.middle_name,
            institution_id=profile.institution_id,
            group_emis_id=profile.group_emis_id,
            group_name=profile.group_name,
            current_semester=profile.current_semester,
            curriculum_id=profile.curriculum_id,
        )


class EmisSubjectResponse(BaseModel):
    """EmisSubject."""

    emis_subject_id: int
    name_uz: str
    name_ru: str
    name_en: str

    @classmethod
    def from_contract(cls, subject: EmisSubject) -> "EmisSubjectResponse":
        """Build the response from the contract dataclass."""
        return cls(
            emis_subject_id=subject.emis_subject_id,
            name_uz=subject.name_uz,
            name_ru=subject.name_ru,
            name_en=subject.name_en,
        )


class EmisMarkResponse(BaseModel):
    """EmisMark."""

    type: EmisMarkType
    date: date
    value: int


class EmisSubjectRatingsResponse(BaseModel):
    """EmisSubjectRatings."""

    emis_subject_id: int
    semester: int
    semester_rating: int | None
    marks: list[EmisMarkResponse]
    payload_hash: str

    @classmethod
    def from_contract(cls, ratings: EmisSubjectRatings) -> "EmisSubjectRatingsResponse":
        """Build the response from the contract dataclass."""
        return cls(
            emis_subject_id=ratings.emis_subject_id,
            semester=ratings.semester,
            semester_rating=ratings.semester_rating,
            marks=[
                EmisMarkResponse(type=m.type, date=m.date, value=m.value)
                for m in ratings.marks
            ],
            payload_hash=ratings.payload_hash,
        )
