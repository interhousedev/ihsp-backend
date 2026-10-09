"""JSON shapes of the internal EMIS gateway (the contract dataclasses as JSON)."""

from datetime import date, time
from typing import Literal

from app.shared.contracts.emis import (
    EmisClass,
    EmisClassHour,
    EmisMarkType,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
    EmisTeacher,
    EmisTopic,
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


class EmisClassHourResponse(BaseModel):
    """EmisClassHour: ``pair_number`` is 0-based, times are ``HH:MM``."""

    pair_number: int
    begin_time: time
    end_time: time

    @classmethod
    def from_contract(cls, hour: EmisClassHour) -> "EmisClassHourResponse":
        """Build the response from the contract dataclass."""
        return cls(
            pair_number=hour.pair_number,
            begin_time=hour.begin_time,
            end_time=hour.end_time,
        )


class EmisTeacherResponse(BaseModel):
    """EmisTeacher."""

    emis_id: int | None
    first_name: str
    last_name: str
    middle_name: str | None

    @classmethod
    def from_contract(cls, teacher: EmisTeacher) -> "EmisTeacherResponse":
        """Build the response from the contract dataclass."""
        return cls(
            emis_id=teacher.emis_id,
            first_name=teacher.first_name,
            last_name=teacher.last_name,
            middle_name=teacher.middle_name,
        )


class EmisTopicResponse(BaseModel):
    """EmisTopic."""

    name: str
    description: str | None
    topic_file_url: str | None
    homework_file_url: str | None
    video_url: str | None

    @classmethod
    def from_contract(cls, topic: EmisTopic) -> "EmisTopicResponse":
        """Build the response from the contract dataclass."""
        return cls(
            name=topic.name,
            description=topic.description,
            topic_file_url=topic.topic_file_url,
            homework_file_url=topic.homework_file_url,
            video_url=topic.video_url,
        )


class EmisClassResponse(BaseModel):
    """EmisClass: ``pair_number`` is 0-based, ``subgroup`` is the student's own half."""

    class_id: int
    date: date
    pair_number: int
    subject: EmisSubjectResponse
    teacher: EmisTeacherResponse | None
    room: str | None
    subgroup: Literal[1, 2] | None
    kind: Literal["lecture", "practice", "midterm", "final", "other"]
    topic: EmisTopicResponse | None

    @classmethod
    def from_contract(cls, item: EmisClass) -> "EmisClassResponse":
        """Build the response from the contract dataclass."""
        return cls(
            class_id=item.class_id,
            date=item.date,
            pair_number=item.pair_number,
            subject=EmisSubjectResponse.from_contract(item.subject),
            teacher=(
                EmisTeacherResponse.from_contract(item.teacher)
                if item.teacher
                else None
            ),
            room=item.room,
            subgroup=item.subgroup,
            kind=item.kind,
            topic=EmisTopicResponse.from_contract(item.topic) if item.topic else None,
        )
