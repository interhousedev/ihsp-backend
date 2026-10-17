"""JSON shapes of the internal EMIS gateway (the contract dataclasses as JSON)."""

from datetime import date, time
from typing import Literal

from app.shared.contracts.emis import (
    EmisCertificate,
    EmisClass,
    EmisClassHour,
    EmisCurriculum,
    EmisCurriculumItem,
    EmisCurriculumSubject,
    EmisDirection,
    EmisMarkType,
    EmisName,
    EmisProfile,
    EmisSemesterDates,
    EmisSemesterSubject,
    EmisSubject,
    EmisSubjectRatings,
    EmisTeacher,
    EmisTopic,
    EmisYear,
)

from pydantic import BaseModel


class EmisCertificateResponse(BaseModel):
    """EmisCertificate: a CEFR or national certificate of the EMIS profile."""

    kind: Literal["cefr", "national"]
    level: str | None
    score: float | None
    percent: float | None
    subject: str | None
    issued_on: date | None
    expires_on: date | None
    serial: str | None
    url: str | None

    @classmethod
    def from_contract(cls, item: EmisCertificate) -> "EmisCertificateResponse":
        """Build the response from the contract dataclass."""
        return cls(
            kind=item.kind,
            level=item.level,
            score=item.score,
            percent=item.percent,
            subject=item.subject,
            issued_on=item.issued_on,
            expires_on=item.expires_on,
            serial=item.serial,
            url=item.url,
        )


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
    absent_dates: list[date] | None = None
    absence_total: int | None = None

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
            absent_dates=(
                None if ratings.absent_dates is None else list(ratings.absent_dates)
            ),
            absence_total=ratings.absence_total,
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


class EmisNameResponse(BaseModel):
    """EmisName: a language EMIS left empty is ``""``."""

    uz: str
    ru: str
    en: str

    @classmethod
    def from_contract(cls, name: EmisName) -> "EmisNameResponse":
        """Build the response from the contract dataclass."""
        return cls(uz=name.uz, ru=name.ru, en=name.en)


class EmisDirectionResponse(BaseModel):
    """EmisDirection."""

    emis_id: int | None
    name: str | None
    code: str | None

    @classmethod
    def from_contract(cls, direction: EmisDirection) -> "EmisDirectionResponse":
        """Build the response from the contract dataclass."""
        return cls(emis_id=direction.emis_id, name=direction.name, code=direction.code)


class EmisYearResponse(BaseModel):
    """EmisYear: the dates are ISO ``YYYY-MM-DD``."""

    code: str | None
    name: str | None
    from_date: date | None
    to_date: date | None

    @classmethod
    def from_contract(cls, year: EmisYear) -> "EmisYearResponse":
        """Build the response from the contract dataclass."""
        return cls(
            code=year.code,
            name=year.name,
            from_date=year.from_date,
            to_date=year.to_date,
        )


class EmisSemesterDatesResponse(BaseModel):
    """EmisSemesterDates: ``number`` is 1-based, the dates are ISO."""

    number: int
    starts_on: date
    ends_on: date

    @classmethod
    def from_contract(cls, semester: EmisSemesterDates) -> "EmisSemesterDatesResponse":
        """Build the response from the contract dataclass."""
        return cls(
            number=semester.number,
            starts_on=semester.starts_on,
            ends_on=semester.ends_on,
        )


class EmisCurriculumSubjectResponse(BaseModel):
    """EmisCurriculumSubject."""

    emis_subject_id: int
    name: EmisNameResponse
    subject_type_id: int | None
    study_hours: int | None

    @classmethod
    def from_contract(
        cls, subject: EmisCurriculumSubject
    ) -> "EmisCurriculumSubjectResponse":
        """Build the response from the contract dataclass."""
        return cls(
            emis_subject_id=subject.emis_subject_id,
            name=EmisNameResponse.from_contract(subject.name),
            subject_type_id=subject.subject_type_id,
            study_hours=subject.study_hours,
        )


class EmisSemesterSubjectResponse(BaseModel):
    """EmisSemesterSubject."""

    semester_number: int
    emis_subject_id: int
    name: EmisNameResponse
    subject_type_id: int | None
    study_hours: int | None
    class_hours: int | None
    independent_hours: int | None
    is_separated: bool

    @classmethod
    def from_contract(
        cls, subject: EmisSemesterSubject
    ) -> "EmisSemesterSubjectResponse":
        """Build the response from the contract dataclass."""
        return cls(
            semester_number=subject.semester_number,
            emis_subject_id=subject.emis_subject_id,
            name=EmisNameResponse.from_contract(subject.name),
            subject_type_id=subject.subject_type_id,
            study_hours=subject.study_hours,
            class_hours=subject.class_hours,
            independent_hours=subject.independent_hours,
            is_separated=subject.is_separated,
        )


class EmisCurriculumItemResponse(BaseModel):
    """EmisCurriculumItem: an exam or a vocational subject."""

    emis_id: int | None
    name: EmisNameResponse
    study_hours: int | None

    @classmethod
    def from_contract(cls, item: EmisCurriculumItem) -> "EmisCurriculumItemResponse":
        """Build the response from the contract dataclass."""
        return cls(
            emis_id=item.emis_id,
            name=EmisNameResponse.from_contract(item.name),
            study_hours=item.study_hours,
        )


class EmisCurriculumResponse(BaseModel):
    """EmisCurriculum: the group's curriculum with ISO dates."""

    emis_id: int
    name: str
    direction: EmisDirectionResponse | None
    speciality: EmisNameResponse | None
    edu_form: str | None
    language_code: str | None
    rating_min: int | None
    rating_max: int | None
    start_year: EmisYearResponse | None
    end_year: EmisYearResponse | None
    semesters_count: int | None
    status: str | None
    semesters: list[EmisSemesterDatesResponse]
    subjects: list[EmisCurriculumSubjectResponse]
    semester_subjects: list[EmisSemesterSubjectResponse]
    exams: list[EmisCurriculumItemResponse]
    vocational_subjects: list[EmisCurriculumItemResponse]

    @classmethod
    def from_contract(cls, curriculum: EmisCurriculum) -> "EmisCurriculumResponse":
        """Build the response from the contract dataclass."""
        return cls(
            emis_id=curriculum.emis_id,
            name=curriculum.name,
            direction=(
                EmisDirectionResponse.from_contract(curriculum.direction)
                if curriculum.direction
                else None
            ),
            speciality=(
                EmisNameResponse.from_contract(curriculum.speciality)
                if curriculum.speciality
                else None
            ),
            edu_form=curriculum.edu_form,
            language_code=curriculum.language_code,
            rating_min=curriculum.rating_min,
            rating_max=curriculum.rating_max,
            start_year=(
                EmisYearResponse.from_contract(curriculum.start_year)
                if curriculum.start_year
                else None
            ),
            end_year=(
                EmisYearResponse.from_contract(curriculum.end_year)
                if curriculum.end_year
                else None
            ),
            semesters_count=curriculum.semesters_count,
            status=curriculum.status,
            semesters=[
                EmisSemesterDatesResponse.from_contract(s) for s in curriculum.semesters
            ],
            subjects=[
                EmisCurriculumSubjectResponse.from_contract(s)
                for s in curriculum.subjects
            ],
            semester_subjects=[
                EmisSemesterSubjectResponse.from_contract(s)
                for s in curriculum.semester_subjects
            ],
            exams=[
                EmisCurriculumItemResponse.from_contract(e) for e in curriculum.exams
            ],
            vocational_subjects=[
                EmisCurriculumItemResponse.from_contract(v)
                for v in curriculum.vocational_subjects
            ],
        )
