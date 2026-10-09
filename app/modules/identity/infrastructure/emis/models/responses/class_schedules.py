"""EMIS class-schedules response: the student's classes, one item per day."""

from pydantic import BaseModel, Field


class NameV1DTO(BaseModel):
    """A name in the three languages; EMIS sends an empty string for a missing one."""

    uz: str | None = None
    ru: str | None = None
    en: str | None = None


class SubjectV1DTO(BaseModel):
    """``edu_subject``: only the id and the names are used."""

    id: int
    name: NameV1DTO


class ClassTypeV1DTO(BaseModel):
    """``class_type``: "Ma'ruza", "Amaliyot", "Oraliq nazorat", "Yakuniy nazorat"."""

    name: str | None = None


class CitizenV1DTO(BaseModel):
    """The person behind a teacher."""

    first_name: str = ""
    middle_name: str | None = None
    last_name: str = ""


class TeacherV1DTO(BaseModel):
    """``teacher``: the id and the person's names."""

    id: int | None = None
    citizen: CitizenV1DTO


class RoomV1DTO(BaseModel):
    """``room``: "23", "003", "Klaster", "Coworking 1"."""

    name: str | None = None


class TopicV1DTO(BaseModel):
    """``topic``: often null; the URLs may be missing or empty."""

    name: str | None = None
    description: str | None = None
    topic_file_url: str | None = None
    homework_file_url: str | None = None
    video_url: str | None = None


class ClassTeacherV1DTO(BaseModel):
    """One teacher row of a class: the subject, type, room, half and topic."""

    edu_subject: SubjectV1DTO | None = None
    class_type: ClassTypeV1DTO | None = None
    teacher: TeacherV1DTO | None = None
    room: RoomV1DTO | None = None
    group_number: int | None = None
    topic: TopicV1DTO | None = None


class ClassV1DTO(BaseModel):
    """One class. ``is_seperated`` (sic) means the group is taught in halves."""

    id: int
    is_seperated: bool | None = None
    pair_number: int
    teachers: list[ClassTeacherV1DTO] | None = None


class DayV1DTO(BaseModel):
    """One day; ``classes`` is null when there are no lessons."""

    date: str
    classes: list[ClassV1DTO] | None = None


class ClassSchedulesV1DTO(BaseModel):
    """The body of ``GET student-profiles/class-schedules/`` (a ``results`` list)."""

    results: list[DayV1DTO] = Field(default_factory=list)
    total_pages: int | None = None
