"""Schemas of the staff routes of a teacher's subjects and their materials."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    SubjectMaterialCreateBody,
    SubjectMaterialResponse,
)
from app.modules.notebooks.application.staff_subject_materials import (
    SubjectMaterialsView,
)
from app.modules.notebooks.application.teaching_directory import (
    TeachingGroup,
    TeachingSubject,
)

from pydantic import BaseModel, Field


class StaffSubjectGroupResponse(BaseModel):
    """A group, or a subgroup, the teacher teaches a subject to."""

    group_id: UUID
    group_name: str
    subgroup: int | None

    @classmethod
    def from_group(cls, group: TeachingGroup) -> "StaffSubjectGroupResponse":
        """The response of one taught group."""
        return cls(
            group_id=group.group_id,
            group_name=group.group_name,
            subgroup=group.subgroup,
        )


class StaffSubjectResponse(BaseModel):
    """A subject the teacher teaches this term."""

    subject_id: UUID
    name: str
    groups: list[StaffSubjectGroupResponse]

    @classmethod
    def from_subject(cls, subject: TeachingSubject) -> "StaffSubjectResponse":
        """The response of one taught subject."""
        return cls(
            subject_id=subject.subject_id,
            name=subject.name,
            groups=[StaffSubjectGroupResponse.from_group(g) for g in subject.groups],
        )


class StaffSubjectMaterialCreateBody(SubjectMaterialCreateBody):
    """A material for all the teacher's groups, or (with `group_id`) for one group."""

    group_id: UUID | None = None
    subgroup: int | None = Field(default=None, ge=1, le=2)


class StaffGroupMaterialResponse(SubjectMaterialResponse):
    """A material of one group (and subgroup)."""

    group_id: UUID
    group_name: str
    subgroup: int | None


class StaffSubjectMaterialsResponse(BaseModel):
    """The three tiers of a subject: administration, mine, per group."""

    subject: StaffSubjectResponse
    admin: list[SubjectMaterialResponse]
    mine: list[SubjectMaterialResponse]
    groups: list[StaffGroupMaterialResponse]

    @classmethod
    def from_view(cls, view: SubjectMaterialsView) -> "StaffSubjectMaterialsResponse":
        """The response of a subject's materials."""
        names = {g.group_id: g.group_name for g in view.subject.groups}
        return cls(
            subject=StaffSubjectResponse.from_subject(view.subject),
            admin=[SubjectMaterialResponse.from_entity(x) for x in view.admin],
            mine=[SubjectMaterialResponse.from_entity(x) for x in view.mine],
            groups=[
                StaffGroupMaterialResponse(
                    **SubjectMaterialResponse.from_entity(x).model_dump(),
                    group_id=x.group_id,
                    group_name=names.get(x.group_id, str(x.group_id)),
                    subgroup=x.subgroup,
                )
                for x in view.groups
                if x.group_id is not None
            ],
        )
