"""Response models of the `/v1/admin` composition endpoints."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.composition.shared_schemas import (
    AdminUserResponse,
    AuditItemResponse,
    GroupItemResponse,
    LessonItemResponse,
    PersonRefResponse,
    RoleName,
    SemesterGradesResponse,
    SessionItemResponse,
    StudentAttendanceResponse,
    StudentProfileResponse,
    TelegramAccountResponse,
)

from pydantic import BaseModel


class SyncRunItemResponse(BaseModel):
    """`SyncRunItem`."""

    id: UUID
    started_at: dt.datetime
    finished_at: dt.datetime | None
    status: str
    stats: dict[str, int | float]


class AudienceResponse(BaseModel):
    """`Audience` of a broadcast."""

    everyone: bool
    roles: list[RoleName]
    group_ids: list[UUID]
    semesters: list[int]


class BroadcastStatsResponse(BaseModel):
    """Delivery counters of a broadcast."""

    total: int
    sent: int
    failed: int
    blocked: int


class BroadcastItemResponse(BaseModel):
    """`BroadcastItem`."""

    id: UUID
    title: str
    text: str
    media_file_ids: list[UUID]
    audience: AudienceResponse
    status: Literal["draft", "scheduled", "sending", "sent", "cancelled"]
    scheduled_at: dt.datetime | None
    created_via: Literal["ui", "assistant"]
    author: PersonRefResponse
    stats: BroadcastStatsResponse | None
    created_at: dt.datetime


class TodayCountsResponse(BaseModel):
    """Lesson counters of today."""

    lessons: int
    cancelled: int
    teacher_needed: int


class MissingAttendanceRowResponse(BaseModel):
    """A teacher and how many finished lessons lack attendance."""

    teacher: PersonRefResponse
    count: int


class SyncOverviewResponse(BaseModel):
    """EMIS sync state."""

    last_run: SyncRunItemResponse | None
    needs_reauth: int


class AdminDashboardResponse(BaseModel):
    """`AdminDashboard`."""

    today: TodayCountsResponse
    missing_attendance: list[MissingAttendanceRowResponse]
    sync: SyncOverviewResponse
    scheduled_broadcasts: list[BroadcastItemResponse]


class GroupStatsItemResponse(BaseModel):
    """One row of `GET /v1/admin/groups/stats`."""

    group_id: UUID
    attendance_rate: float | None
    average_gpa: float | None


class Student360ProfileResponse(StudentProfileResponse):
    """`StudentProfile` plus the account status and roles."""

    status: str
    roles: list[RoleName]


class Student360Response(BaseModel):
    """`Student360`."""

    profile: Student360ProfileResponse
    timetable_week: list[LessonItemResponse]
    grades: SemesterGradesResponse
    attendance: StudentAttendanceResponse
    telegram: list[TelegramAccountResponse]
    sessions: list[SessionItemResponse]
    audit: list[AuditItemResponse]


class TeacherProfileResponse(BaseModel):
    """`TeacherProfile`."""

    user: AdminUserResponse
    timetable_week: list[LessonItemResponse]
    missing_attendance: list[LessonItemResponse]
    curated_groups: list[GroupItemResponse]
