"""Schemas of the subject routes."""

from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import ApiModel
from app.interfaces.http.v1.admin_sync.schemas import TermChoice

from pydantic import BaseModel, Field


class SubjectNameBody(BaseModel):
    """Names of a subject in the three languages (empty string = not set)."""

    uz: str = ""
    ru: str = ""
    en: str = ""


class SubjectCreateBody(BaseModel):
    """Body of POST /v1/admin/subjects."""

    name: SubjectNameBody
    short_name: str | None = Field(default=None, max_length=64)
    emis_subject_id: int | None = None
    can_be_divided: bool = False


class SubjectPatchBody(BaseModel):
    """Body of PATCH /v1/admin/subjects/{id}."""

    name: SubjectNameBody | None = None
    short_name: str | None = Field(default=None, max_length=64)
    emis_subject_id: int | None = None
    can_be_divided: bool | None = None


class SubjectNameResponse(ApiModel):
    """Subject names."""

    uz: str = ""
    ru: str = ""
    en: str = ""


class SubjectResponse(ApiModel):
    """Subject."""

    id: UUID
    name: SubjectNameResponse
    short_name: str | None
    emis_subject_id: int | None
    can_be_divided: bool


class SubjectPersonResponse(ApiModel):
    """A teacher or a group that has the subject."""

    id: UUID
    name: str


class SubjectPeopleResponse(ApiModel):
    """Teachers and groups of the subject in the current term."""

    teachers: list[SubjectPersonResponse]
    groups: list[SubjectPersonResponse]


class EmisPullBody(BaseModel):
    """Body of POST /v1/admin/subjects/{id}/emis-pull.

    ``full`` replaces the EMIS materials of the subject's lessons, ``soft`` only
    fills lessons without any material. ``terms`` absent = the current term.
    """

    mode: Literal["full", "soft"] = "full"
    teacher_id: UUID | None = None
    group_id: UUID | None = None
    terms: list[TermChoice] | None = Field(default=None, min_length=1, max_length=10)
