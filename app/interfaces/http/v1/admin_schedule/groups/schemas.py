"""Schemas of the group routes (also used by the staff group routes)."""

from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import (
    ApiModel,
    PersonRefResponse,
)

from pydantic import BaseModel, Field


class GroupCreateBody(BaseModel):
    """Body of POST /v1/admin/groups."""

    name: str = Field(min_length=1, max_length=64)
    emis_group_id: int | None = None
    current_semester: int | None = Field(default=None, ge=1, le=12)


class GroupPatchBody(BaseModel):
    """Body of PATCH /v1/admin/groups/{id}; send null to clear curator or head."""

    curator_id: UUID | None = None
    head_student_id: UUID | None = None
    status: Literal["active", "archived"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=64)
    current_semester: int | None = Field(default=None, ge=1, le=12)


class SubgroupAssignmentBody(BaseModel):
    """One student and the subgroup to set (null clears it)."""

    user_id: UUID
    subgroup: Literal[1, 2] | None


class SubgroupsBody(BaseModel):
    """Body of PUT .../subgroups."""

    assignments: list[SubgroupAssignmentBody] = Field(max_length=500)


class GroupItemResponse(ApiModel):
    """GroupItem."""

    id: UUID
    name: str
    slug: str
    current_semester: int | None
    status: Literal["active", "archived"]
    students_count: int
    subgroups_assigned: int
    unregistered_count: int
    curator: PersonRefResponse | None
    head_student: PersonRefResponse | None


class GroupStudentResponse(ApiModel):
    """GroupStudent."""

    user_id: UUID
    first_name: str
    last_name: str
    subgroup: Literal[1, 2] | None
    status: Literal["active", "left"]
    registered: bool


class GroupDetailResponse(GroupItemResponse):
    """GroupDetail."""

    emis_group_id: int | None
    students: list[GroupStudentResponse]
