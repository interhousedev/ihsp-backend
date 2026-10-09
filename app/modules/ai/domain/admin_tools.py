"""The Administration assistant's tools (AI-6) and their arguments.

The tools are forwarded to `AdminToolBackend.call(tool, arguments, actor)`; the
argument names below are the contract with the backend (task I1). Dates are
`YYYY-MM-DD`, ids are UUID strings, `null` values are never sent.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import ToolAccess

from pydantic import BaseModel, ConfigDict, Field

Weekday = Annotated[int, Field(ge=1, le=6)]
Period = Annotated[int, Field(ge=1, le=12)]
Short = Annotated[str, Field(min_length=1, max_length=200)]
RoleName = Literal["student", "teacher", "admin", "lms_admin", "librarian"]
Parity = Literal["every", "odd", "even"]


class AudienceEntry(BaseModel):
    """A group, or one subgroup of it, that attends a lesson."""

    model_config = ConfigDict(extra="forbid")

    group_id: UUID
    subgroup: Literal[1, 2] | None = None


class BroadcastAudience(BaseModel):
    """Who a broadcast goes to."""

    model_config = ConfigDict(extra="forbid")

    everyone: bool = False
    roles: list[RoleName] = Field(default_factory=list)
    group_ids: list[UUID] = Field(default_factory=list)
    semesters: list[int] = Field(default_factory=list)


class SearchUsersArgs(ToolArgs):
    """Find users by name or login."""

    query: Short
    roles: list[RoleName] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=20)


class UserIdArgs(ToolArgs):
    """A single user."""

    user_id: UUID


class ListTeachersArgs(ToolArgs):
    """Teacher accounts."""

    query: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=30)


class ListGroupsArgs(ToolArgs):
    """Groups by status."""

    status: Literal["active", "archived"] | None = None


class GroupIdArgs(ToolArgs):
    """A single group."""

    group_id: UUID


class GetTimetableArgs(ToolArgs):
    """Timetable entries of the current (or given) term for one filter."""

    term_id: UUID | None = None
    group_id: UUID | None = None
    teacher_id: UUID | None = None
    room_id: UUID | None = None


class ListLessonsArgs(ToolArgs):
    """Lessons in a date range."""

    date_from: dt.date = Field(alias="from")
    date_to: dt.date = Field(alias="to")
    group_id: UUID | None = None
    teacher_id: UUID | None = None
    room_id: UUID | None = None
    status: Literal["scheduled", "cancelled"] | None = None
    teacher_needed: bool | None = None


class AttendanceStatsArgs(ToolArgs):
    """Attendance statistics."""

    view: Literal["group", "student", "subject", "teacher"]
    date_from: dt.date = Field(alias="from")
    date_to: dt.date = Field(alias="to")
    group_id: UUID | None = None


class MissingAttendanceArgs(ToolArgs):
    """Lessons without submitted attendance."""

    date_from: dt.date = Field(alias="from")
    date_to: dt.date = Field(alias="to")


class ListBroadcastsArgs(ToolArgs):
    """Broadcasts by status."""

    status: Literal["draft", "scheduled", "sending", "sent", "cancelled"] | None = None


class NoArgs(ToolArgs):
    """A tool without arguments."""


class AuditLogArgs(ToolArgs):
    """Audit events."""

    user_id: UUID | None = None
    type: str | None = Field(default=None, max_length=100)
    date_from: dt.date | None = Field(default=None, alias="from")
    date_to: dt.date | None = Field(default=None, alias="to")
    limit: int = Field(default=20, ge=1, le=50)


class CreateTeacherArgs(ToolArgs):
    """A new teacher account (an activation link is created for the teacher)."""

    last_name: Short
    first_name: Short
    middle_name: str | None = Field(default=None, max_length=200)
    email: Annotated[str, Field(min_length=3, max_length=254)]


class UpdateTeacherArgs(ToolArgs):
    """Changes to a teacher account."""

    teacher_id: UUID
    last_name: str | None = Field(default=None, min_length=1, max_length=200)
    first_name: str | None = Field(default=None, min_length=1, max_length=200)
    middle_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=254)


class CreateGroupArgs(ToolArgs):
    """A new group."""

    name: Short
    emis_group_id: int | None = None
    current_semester: int | None = Field(default=None, ge=1, le=16)


class UpdateGroupArgs(ToolArgs):
    """Changes to a group: curator, head student, status."""

    group_id: UUID
    curator_id: UUID | None = None
    head_student_id: UUID | None = None
    status: Literal["active", "archived"] | None = None


class CreateTimetableEntryArgs(ToolArgs):
    """A new weekly timetable entry."""

    term_id: UUID
    weekday: Weekday
    period: Period
    week_parity: Parity = "every"
    subject_id: UUID
    teacher_id: UUID | None = None
    room_name: str | None = Field(default=None, max_length=100)
    audience: list[AudienceEntry] = Field(min_length=1, max_length=10)
    valid_from: dt.date
    valid_to: dt.date | None = None


class UpdateTimetableEntryArgs(ToolArgs):
    """Changes to a timetable entry; only the sent fields change."""

    entry_id: UUID
    weekday: Weekday | None = None
    period: Period | None = None
    week_parity: Parity | None = None
    subject_id: UUID | None = None
    teacher_id: UUID | None = None
    room_name: str | None = Field(default=None, max_length=100)
    audience: list[AudienceEntry] | None = Field(default=None, max_length=10)
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None


class DeleteTimetableEntryArgs(ToolArgs):
    """Remove a timetable entry."""

    entry_id: UUID


class CreateLessonArgs(ToolArgs):
    """A one-off lesson."""

    date: dt.date
    period: Period
    subject_id: UUID
    teacher_id: UUID | None = None
    room_name: str | None = Field(default=None, max_length=100)
    audience: list[AudienceEntry] = Field(min_length=1, max_length=10)
    topic: str | None = Field(default=None, max_length=300)


class UpdateLessonArgs(ToolArgs):
    """Cancel, move or replace a lesson; only the sent fields change."""

    lesson_id: UUID
    status: Literal["scheduled", "cancelled"] | None = None
    teacher_id: UUID | None = None
    subject_id: UUID | None = None
    room_name: str | None = Field(default=None, max_length=100)
    date: dt.date | None = None
    period: Period | None = None
    topic: str | None = Field(default=None, max_length=300)


class CreateBroadcastDraftArgs(ToolArgs):
    """A broadcast draft; a person reviews and sends it in the admin UI."""

    title: Annotated[str, Field(min_length=1, max_length=200)]
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    audience: BroadcastAudience


@dataclass(frozen=True, slots=True)
class AdminToolDef:
    """One Administration tool: schema, access and sensitive argument names."""

    name: str
    access: ToolAccess
    description: str
    args: type[ToolArgs]
    sensitive: frozenset[str] = frozenset()


def _read(name: str, description: str, args: type[ToolArgs]) -> AdminToolDef:
    return AdminToolDef(name, ToolAccess.READ, description, args)


def _write(
    name: str, description: str, args: type[ToolArgs], *sensitive: str
) -> AdminToolDef:
    return AdminToolDef(name, ToolAccess.WRITE, description, args, frozenset(sensitive))


ADMIN_TOOLS: tuple[AdminToolDef, ...] = (
    _read("search_users", "Find users by name or login.", SearchUsersArgs),
    _read("get_student", "Profile, group and sync state of a student.", UserIdArgs),
    _read("list_teachers", "List teacher accounts.", ListTeachersArgs),
    _read("list_groups", "List groups with curator and head student.", ListGroupsArgs),
    _read("get_group", "A group with its students and subgroups.", GroupIdArgs),
    _read(
        "get_timetable",
        "Timetable entries filtered by group, teacher or room.",
        GetTimetableArgs,
    ),
    _read(
        "list_lessons",
        "Lessons in a date range with optional filters.",
        ListLessonsArgs,
    ),
    _read(
        "attendance_stats", "Attendance statistics for a period.", AttendanceStatsArgs
    ),
    _read(
        "missing_attendance",
        "Finished lessons without attendance.",
        MissingAttendanceArgs,
    ),
    _read(
        "list_broadcasts", "List broadcasts, optionally by status.", ListBroadcastsArgs
    ),
    _read("sync_status", "Last EMIS sync runs and accounts needing re-login.", NoArgs),
    _read("audit_log", "Recent audit events, optionally filtered.", AuditLogArgs),
    _write("create_teacher", "Create a teacher account.", CreateTeacherArgs, "email"),
    _write("update_teacher", "Edit a teacher account.", UpdateTeacherArgs, "email"),
    _write("create_group", "Create a group.", CreateGroupArgs),
    _write(
        "update_group",
        "Change a group's curator, head student or status.",
        UpdateGroupArgs,
        "curator_id",
        "head_student_id",
    ),
    _write(
        "create_timetable_entry",
        "Add a weekly timetable entry.",
        CreateTimetableEntryArgs,
    ),
    _write(
        "update_timetable_entry", "Edit a timetable entry.", UpdateTimetableEntryArgs
    ),
    _write(
        "delete_timetable_entry", "Delete a timetable entry.", DeleteTimetableEntryArgs
    ),
    _write("create_lesson", "Add a one-off lesson.", CreateLessonArgs),
    _write("update_lesson", "Cancel, move or replace one lesson.", UpdateLessonArgs),
    _write(
        "create_broadcast_draft",
        "Create a broadcast draft (never sends).",
        CreateBroadcastDraftArgs,
    ),
)
