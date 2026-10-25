"""Schemas of the admin student routes."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import ApiModel
from app.modules.academic.application.schedule.results import (
    ImportPreviewData,
    ImportRowData,
    StudentItemData,
)
from app.shared.pagination import Page

from pydantic import BaseModel


class GroupRefResponse(BaseModel):
    """A group as {id, name}."""

    id: UUID
    name: str


class StudentItemResponse(BaseModel):
    """StudentItem."""

    user_id: UUID
    login: str | None
    first_name: str
    last_name: str
    group: GroupRefResponse | None
    subgroup: Literal[1, 2] | None
    status: str
    emis_status: str | None
    registered: bool
    synced_at: dt.datetime | None

    @classmethod
    def from_data(cls, data: StudentItemData) -> "StudentItemResponse":
        """Nest the group of the flat read model."""
        group = (
            {"id": data.group_id, "name": data.group_name or ""}
            if data.group_id
            else None
        )
        return cls.model_validate(
            {
                "user_id": data.user_id,
                "login": data.login,
                "first_name": data.first_name,
                "last_name": data.last_name,
                "group": group,
                "subgroup": data.subgroup,
                "status": data.status,
                "emis_status": data.emis_status,
                "registered": data.registered,
                "synced_at": data.synced_at,
            }
        )


StudentPageResponse = Page[StudentItemResponse]


class ImportRowResponse(ApiModel):
    """ImportRow."""

    line: int
    last_name: str
    first_name: str
    middle_name: str | None
    group_name: str
    emis_student_id: int | None
    note: str | None


class ImportPreviewResponse(BaseModel):
    """ImportPreview."""

    import_id: UUID
    new: list[ImportRowResponse]
    changed: list[ImportRowResponse]
    unchanged: int
    conflicts: list[ImportRowResponse]

    @classmethod
    def from_data(cls, data: ImportPreviewData) -> "ImportPreviewResponse":
        """Map the read model of a preview."""

        def rows(items: list[ImportRowData]) -> list[ImportRowResponse]:
            return [ImportRowResponse.model_validate(item) for item in items]

        return cls(
            import_id=data.import_id,
            new=rows(data.new),
            changed=rows(data.changed),
            unchanged=data.unchanged,
            conflicts=rows(data.conflicts),
        )


class ImportConfirmResponse(ApiModel):
    """Result of confirming an import."""

    created: int
    updated: int
    skipped: int
