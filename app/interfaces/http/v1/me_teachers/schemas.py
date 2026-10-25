"""Response models of /v1/me/teachers."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.schedule.get_my_teachers import (
    MyTeacherData,
    TeacherLessonData,
    TeacherSubjectData,
)
from app.modules.academic.application.schedule.get_teacher_timetable import (
    TeacherSlot,
)
from app.shared.contracts.identity import TeacherContacts

from pydantic import BaseModel


class TeacherLessonResponse(BaseModel):
    """One lesson of a teacher."""

    date: dt.date
    weekday: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject_id: UUID
    subject: str
    group: str | None
    room: str | None
    lesson_id: UUID | None

    @classmethod
    def of(cls, data: TeacherLessonData | None) -> "TeacherLessonResponse | None":
        """Map the use case result."""
        if data is None:
            return None
        return cls(
            date=data.date,
            weekday=data.weekday,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
            subject_id=data.subject_id,
            subject=data.subject,
            group=data.group,
            room=data.room,
            lesson_id=data.lesson_id,
        )

    @classmethod
    def many(cls, items: list[TeacherLessonData]) -> "list[TeacherLessonResponse]":
        """Map a list of lessons."""
        return [r for r in (cls.of(item) for item in items) if r]


class TeacherSubjectRefResponse(BaseModel):
    """A subject a teacher teaches the student."""

    id: UUID
    name: str

    @classmethod
    def of(cls, data: TeacherSubjectData) -> "TeacherSubjectRefResponse":
        """Map the use case result."""
        return cls(id=data.id, name=data.name)


class MyTeacherResponse(BaseModel):
    """A teacher of the student."""

    id: UUID
    first_name: str
    last_name: str
    middle_name: str | None
    photo_url: str | None
    subjects: list[str]
    subject_refs: list[TeacherSubjectRefResponse]
    contacts: TeacherContacts
    teaching_now: bool
    current: TeacherLessonResponse | None
    next: TeacherLessonResponse | None
    week: list[TeacherLessonResponse]
    upcoming: list[TeacherLessonResponse]

    @classmethod
    def of(cls, data: MyTeacherData) -> "MyTeacherResponse":
        """Map the use case result."""
        return cls(
            id=data.id,
            first_name=data.first_name,
            last_name=data.last_name,
            middle_name=data.middle_name,
            photo_url=data.photo_url,
            subjects=data.subjects,
            subject_refs=[TeacherSubjectRefResponse.of(s) for s in data.subject_refs],
            contacts=data.contacts,
            teaching_now=data.teaching_now,
            current=TeacherLessonResponse.of(data.current),
            next=TeacherLessonResponse.of(data.next),
            week=TeacherLessonResponse.many(data.week),
            upcoming=TeacherLessonResponse.many(data.upcoming),
        )


class TeacherSlotResponse(BaseModel):
    """One lesson in a teacher's timetable: no student data."""

    id: UUID
    date: dt.date
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject_id: UUID
    subject_name: str
    room: str | None
    group: str | None
    mine: bool
    status: str
    lesson_id: UUID | None

    @classmethod
    def of(cls, slot: TeacherSlot) -> "TeacherSlotResponse":
        """Map the use case result."""
        return cls(
            id=slot.id,
            date=slot.date,
            starts_at=slot.starts_at,
            ends_at=slot.ends_at,
            subject_id=slot.subject_id,
            subject_name=slot.subject_name,
            room=slot.room,
            group=slot.group,
            mine=slot.mine,
            status=slot.status,
            lesson_id=slot.lesson_id,
        )
