"""Course settings routes: read, change, join code, link check."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import InviteCodeResponse, respond
from app.modules.lms.application.authoring.settings_views import (
    CourseSettingsView,
    LinkJobView,
    LinkReportView,
)

from pydantic import BaseModel, Field


class NavigationItem(BaseModel):
    """A section of the course page and whether learners see it."""

    key: str = Field(max_length=32)
    hidden: bool = False


class SettingsDetailsBody(BaseModel):
    """Partial change; omitted fields stay as they are, `null` clears nullable ones."""

    code: str | None = Field(default=None, max_length=64)
    friendly_name: str | None = Field(default=None, max_length=400)
    summary: str | None = Field(default=None, max_length=1000)
    cover_file_id: UUID | None = None
    banner_file_id: UUID | None = None
    accent_color: str | None = Field(default=None, max_length=16)
    language: str | None = Field(default=None, max_length=8)
    level: Literal["beginner", "intermediate", "advanced"] | None = None
    workload_hours_per_week: int | None = None
    duration_weeks: int | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    outcomes: list[str] | None = Field(default=None, max_length=50)
    requirements: list[str] | None = Field(default=None, max_length=50)
    audience: list[str] | None = Field(default=None, max_length=50)
    audience_scope: str | None = Field(default=None, max_length=16)
    audience_group_ids: list[UUID] | None = Field(default=None, max_length=200)
    enrolment_open: bool | None = None
    enrolment_starts_at: datetime | None = None
    enrolment_ends_at: datetime | None = None
    navigation: list[NavigationItem] | None = Field(default=None, max_length=32)


NOT_NULLABLE = frozenset(
    {
        "summary",
        "language",
        "tags",
        "outcomes",
        "requirements",
        "audience",
        "audience_scope",
        "audience_group_ids",
        "enrolment_open",
        "navigation",
    }
)


async def get_settings(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> CourseSettingsView:
    """Return every setting, the join code and the course counts."""
    return await authoring.get_course_settings.execute(actor, course_id)


async def update_details(
    course_id: UUID,
    body: SettingsDetailsBody,
    actor: ActorDep,
    authoring: AuthoringDep,
) -> CourseSettingsView:
    """Change the sent fields; invalid values are a 422 naming the field."""
    changes = {
        name: getattr(body, name)
        for name in body.model_fields_set
        if not (name in NOT_NULLABLE and getattr(body, name) is None)
    }
    if "navigation" in changes:
        changes["navigation"] = [i.model_dump() for i in body.navigation or []]
    if "audience_group_ids" in changes:
        changes["audience_group_ids"] = [str(i) for i in body.audience_group_ids or []]
    return await authoring.update_course_details.execute(actor, course_id, changes)


async def regenerate_join_code(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> InviteCodeResponse:
    """Replace the join code; the old one stops working."""
    view = await authoring.regenerate_join_code.execute(actor, course_id)
    return respond(InviteCodeResponse, view)


async def start_link_check(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> LinkJobView:
    """Queue a check of the links in the step drafts."""
    return await authoring.start_link_check.execute(actor, course_id)


async def get_link_report(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> LinkReportView:
    """Return the last link report (`idle` when none)."""
    return await authoring.get_link_report.execute(actor, course_id)
