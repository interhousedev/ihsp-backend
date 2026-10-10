"""EMIS contracts (provider: identity process gateway)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from app.shared.base_error import BaseError
from app.shared.lesson_kind import LessonKind


class EmisMarkType(StrEnum):
    """Kinds of marks in EMIS."""

    LESSON = "lesson"
    MIDTERM = "midterm"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class EmisProfile:
    """Student profile from EMIS."""

    emis_student_id: int
    first_name: str
    last_name: str
    middle_name: str | None
    institution_id: int
    group_emis_id: int
    group_name: str  # normalized, e.g. "2TN2"
    current_semester: int | None
    curriculum_id: int | None


@dataclass(frozen=True, slots=True)
class EmisSubject:
    """A subject of the student's curriculum."""

    emis_subject_id: int
    name_uz: str
    name_ru: str
    name_en: str


@dataclass(frozen=True, slots=True)
class EmisMark:
    """One mark."""

    type: EmisMarkType
    date: dt.date
    value: int


@dataclass(frozen=True, slots=True)
class EmisSubjectRatings:
    """Marks and the semester rating of one subject."""

    emis_subject_id: int
    semester: int
    semester_rating: int | None
    marks: tuple[EmisMark, ...]
    payload_hash: str  # sha256 of the canonical JSON of this response


@dataclass(frozen=True, slots=True)
class EmisClassHour:
    """One bell of EMIS ``class-hours``; ``pair_number`` is 0-based (0 = period 1)."""

    pair_number: int
    begin_time: dt.time
    end_time: dt.time


@dataclass(frozen=True, slots=True)
class EmisTeacher:
    """A teacher as the EMIS timetable names them (names normalized like students')."""

    emis_id: int | None
    first_name: str
    last_name: str
    middle_name: str | None


@dataclass(frozen=True, slots=True)
class EmisTopic:
    """The topic a teacher entered for a class, with the files and video around it."""

    name: str
    description: str | None = None
    topic_file_url: str | None = None
    homework_file_url: str | None = None
    video_url: str | None = None


@dataclass(frozen=True, slots=True)
class EmisClass:
    """One class of the student's timetable on a date (``class-schedules``).

    ``pair_number`` is 0-based like ``EmisClassHour.pair_number``. ``subgroup`` is the
    student's own half (1 or 2) when EMIS split the class, else None: the other half's
    slot only reaches IHSP through a student of that half.
    """

    class_id: int
    date: dt.date
    pair_number: int
    subject: EmisSubject
    teacher: EmisTeacher | None
    room: str | None
    subgroup: Literal[1, 2] | None
    kind: LessonKind
    topic: EmisTopic | None = None


@dataclass(frozen=True, slots=True)
class EmisName:
    """A name in the three languages; a language EMIS left empty is ``""``."""

    uz: str = ""
    ru: str = ""
    en: str = ""


@dataclass(frozen=True, slots=True)
class EmisYear:
    """An academic year of the curriculum (``start_year`` / ``end_year``)."""

    code: str | None
    name: str | None
    from_date: dt.date | None
    to_date: dt.date | None


@dataclass(frozen=True, slots=True)
class EmisDirection:
    """The education direction of the curriculum (``edu_direction``)."""

    emis_id: int | None
    name: str | None
    code: str | None


@dataclass(frozen=True, slots=True)
class EmisSemesterDates:
    """One semester of the curriculum: 1-based number and its school dates."""

    number: int
    starts_on: dt.date
    ends_on: dt.date


@dataclass(frozen=True, slots=True)
class EmisCurriculumSubject:
    """A subject of the whole curriculum with its total hours (``edu_subject``).

    ``subject_type_id``: 1 general, 2 advanced (in-depth), 3 vocational, 4 unified.
    """

    emis_subject_id: int
    name: EmisName
    subject_type_id: int | None
    study_hours: int | None


@dataclass(frozen=True, slots=True)
class EmisSemesterSubject:
    """A subject taught in one semester with its hours (``semester_edu_subjects``).

    ``is_separated`` is EMIS's flag (sent as ``is_seperated``): the class is taught
    in two halves.
    """

    semester_number: int
    emis_subject_id: int
    name: EmisName
    subject_type_id: int | None
    study_hours: int | None
    class_hours: int | None
    independent_hours: int | None
    is_separated: bool


@dataclass(frozen=True, slots=True)
class EmisCurriculumItem:
    """An exam or a vocational subject of the curriculum: name and hours."""

    emis_id: int | None
    name: EmisName
    study_hours: int | None


@dataclass(frozen=True, slots=True)
class EmisCurriculum:
    """The student's curriculum (``student-profiles/curriculum/``), group level.

    ``rating_min`` and ``rating_max`` are the rating scale (``rating_type``).
    ``semesters`` lists the dates by semester number; the per-semester subjects are in
    ``semester_subjects``; ``subjects`` holds the totals over the whole curriculum.
    Empty strings from EMIS are mapped to None (or to ``""`` inside ``EmisName``).
    """

    emis_id: int
    name: str
    direction: EmisDirection | None
    speciality: EmisName | None
    edu_form: str | None
    language_code: str | None
    rating_min: int | None
    rating_max: int | None
    start_year: EmisYear | None
    end_year: EmisYear | None
    semesters_count: int | None
    status: str | None
    semesters: tuple[EmisSemesterDates, ...]
    subjects: tuple[EmisCurriculumSubject, ...]
    semester_subjects: tuple[EmisSemesterSubject, ...]
    exams: tuple[EmisCurriculumItem, ...]
    vocational_subjects: tuple[EmisCurriculumItem, ...]


class EmisAuthFailed(BaseError):
    """EMIS rejected the stored credentials."""

    code = "emis/auth-failed"
    status = 401
    message_key = "emis-auth-failed"


class EmisUnavailable(BaseError):
    """EMIS did not answer or answered with a server error."""

    code = "emis/unavailable"
    status = 503
    message_key = "emis-unavailable"


class EmisCredentialsMissing(EmisUnavailable):
    """The student's EMIS login is not stored: this student cannot be used.

    A 503 like EmisUnavailable for the student-facing calls, but under its own type so
    that a caller reading a group (the curriculum sync) can skip the student and try the
    next one. Only a real outage stays ``emis/unavailable``.
    """

    code = "emis/credentials-missing"
    message_key = "emis-credentials-missing"


class EmisSource(Protocol):
    """What academic sync uses to read EMIS."""

    async def profile(self, user_id: UUID) -> EmisProfile:
        """Return the student's profile."""
        ...

    async def subjects(self, user_id: UUID) -> list[EmisSubject]:
        """Return the student's subjects."""
        ...

    async def curriculum(self, user_id: UUID) -> EmisCurriculum:
        """Return the full curriculum of the student: semesters, hours, exams."""
        ...

    async def ratings(
        self, user_id: UUID, emis_subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Return marks and rating of one subject in one semester."""
        ...

    async def class_hours(self, user_id: UUID) -> list[EmisClassHour]:
        """Return the bells of the lyceum (the same for every student)."""
        ...

    async def timetable(
        self, user_id: UUID, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Return the student's classes on the dates begin..end (inclusive)."""
        ...
