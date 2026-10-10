"""Response models of /v1/me/teachers."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.schedule.get_my_teachers import (
    MyTeacherData,
    TeacherLessonData,
)
from app.shared.contracts.identity import TeacherContacts

from pydantic import BaseModel


class TeacherLessonResponse(BaseModel):
    """One lesson of a teacher."""

    date: dt.date
    weekday: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject: str
    group: str | None
    room: str | None

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
            subject=data.subject,
            group=data.group,
            room=data.room,
        )


class MyTeacherResponse(BaseModel):
    """A teacher of the student."""

    id: UUID
    first_name: str
    last_name: str
    middle_name: str | None
    subjects: list[str]
    contacts: TeacherContacts
    teaching_now: bool
    current: TeacherLessonResponse | None
    next: TeacherLessonResponse | None
    week: list[TeacherLessonResponse]

    @classmethod
    def of(cls, data: MyTeacherData) -> "MyTeacherResponse":
        """Map the use case result."""
        return cls(
            id=data.id,
            first_name=data.first_name,
            last_name=data.last_name,
            middle_name=data.middle_name,
            subjects=data.subjects,
            contacts=data.contacts,
            teaching_now=data.teaching_now,
            current=TeacherLessonResponse.of(data.current),
            next=TeacherLessonResponse.of(data.next),
            week=[r for r in (TeacherLessonResponse.of(w) for w in data.week) if r],
        )
