"""Schemas of the profile and timetable routes."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import PersonRefResponse
from app.modules.academic.application.schedule.results import StudentProfileData

from pydantic import BaseModel


class GroupRefResponse(BaseModel):
    """A group as {id, name}."""

    id: UUID
    name: str


class StudentProfileResponse(BaseModel):
    """StudentProfile."""

    user_id: UUID
    login: str | None
    first_name: str
    last_name: str
    mailbox: str | None
    group: GroupRefResponse
    subgroup: Literal[1, 2] | None
    curator: PersonRefResponse | None
    head_student: PersonRefResponse | None
    current_semester: int | None
    emis_status: str | None
    synced_at: dt.datetime | None

    @classmethod
    def from_data(cls, data: StudentProfileData) -> "StudentProfileResponse":
        """Nest the group of the flat read model."""
        return cls.model_validate(
            {
                "user_id": data.user_id,
                "login": data.login,
                "first_name": data.first_name,
                "last_name": data.last_name,
                "mailbox": data.mailbox,
                "group": {"id": data.group_id, "name": data.group_name},
                "subgroup": data.subgroup,
                "curator": data.curator,
                "head_student": data.head_student,
                "current_semester": data.current_semester,
                "emis_status": data.emis_status,
                "synced_at": data.synced_at,
            },
            from_attributes=True,
        )
