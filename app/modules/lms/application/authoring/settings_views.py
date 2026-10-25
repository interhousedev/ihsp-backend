"""Read models of the course settings page and the link report."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class SettingsStatsView(BaseModel):
    """Counts shown next to the settings."""

    sections: int
    steps: int
    learners: int
    staff_by_role: dict[str, int]


class CourseSettingsView(BaseModel):
    """`CourseSettings`: everything the settings page edits, plus counts."""

    id: UUID
    slug: str
    lock_version: int
    code: str | None
    friendly_name: str | None
    summary: str
    cover_file_id: UUID | None
    banner_file_id: UUID | None
    accent_color: str | None
    language: str
    level: str | None
    workload_hours_per_week: int | None
    duration_weeks: int | None
    tags: list[str]
    outcomes: list[str]
    requirements: list[str]
    audience: list[str]
    audience_scope: str
    audience_group_ids: list[str]
    enrolment_open: bool
    enrolment_starts_at: datetime | None
    enrolment_ends_at: datetime | None
    navigation: list[dict[str, object]]
    publish_state: str
    visibility: str
    invite_code: str | None
    stats: SettingsStatsView


class LinkResultView(BaseModel):
    """One checked URL."""

    url: str
    step_id: str
    step_title: str
    status_code: int | None
    ok: bool
    error: str | None


class LinkReportView(BaseModel):
    """`LinkReport`: the last link check of a course."""

    status: Literal["idle", "running", "done"]
    job_id: str | None = None
    checked_at: datetime | None = None
    results: list[LinkResultView] = []


class LinkJobView(BaseModel):
    """The queued link check."""

    job_id: str
