"""Read-only Administration tools (AI-6, MCP admin server) over module use cases."""

from typing import Any, Literal, cast

from app.bootstrap.adapters.admin_tools_args import (
    Args,
    day_end,
    day_start,
    invalid,
    limit_arg,
    opt_date,
    opt_uuid,
    uuid_arg,
)
from app.bootstrap.container import Container
from app.interfaces.http.v1.id.schemas import AuditItemResponse
from app.interfaces.mcp.jsonable import to_jsonable, to_jsonable_dict
from app.modules.academic.application.schedule.ports.reader import LessonFilters
from app.modules.admin.domain.broadcast import BroadcastStatus
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus

MAX_LESSONS = 100
AttendanceView = Literal["group", "student", "subject", "teacher"]
ATTENDANCE_VIEWS = frozenset({"group", "student", "subject", "teacher"})


async def search_users(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Find users by name or login."""
    roles = [Role(role) for role in args.get("roles") or []]
    found = await c.identity.directory.search_users(
        str(args.get("query") or ""), roles=roles, limit=limit_arg(args, 10, 20)
    )
    return {"users": to_jsonable(found)}


async def get_student(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """A student's account, group and sync state."""
    user_id = uuid_arg(args, "user_id")
    user = await c.identity.directory.get_user(user_id)
    if user is None or Role.STUDENT not in user.roles:
        return {"found": False}
    student = await c.academic.schedule.queries.get_student(user_id)
    return {"found": True, "user": to_jsonable(user), "student": to_jsonable(student)}


async def list_teachers(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Teacher accounts."""
    status = args.get("status")
    page = await c.identity.auth.list_teachers.execute(
        query=args.get("query") or None,
        status=UserStatus(status) if status else None,
        cursor=None,
        limit=limit_arg(args, 50, 100),
    )
    teachers = [
        {
            "id": user.id,
            "login": user.login,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "status": user.status,
        }
        for user in page.items
    ]
    return {"teachers": to_jsonable(teachers), "has_more": bool(page.next_cursor)}


async def list_groups(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Groups, optionally by status, semester or a name fragment."""
    status = args.get("status")
    groups = await c.academic.schedule.list_groups.execute(status or None)
    semester = args.get("semester")
    query = str(args.get("query") or "").casefold()
    shown = [
        group
        for group in groups
        if (semester in (None, "") or group.current_semester == int(semester))
        and query in group.name.casefold()
    ]
    return {"groups": to_jsonable(shown)}


async def get_group(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """A group with students and subgroups."""
    detail = await c.academic.schedule.get_group_detail.execute(
        actor, uuid_arg(args, "group_id")
    )
    return to_jsonable_dict(detail)


async def get_timetable(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Timetable entries filtered by term, group, teacher or room."""
    entries = await c.academic.schedule.list_entries.execute(
        actor,
        term_id=opt_uuid(args, "term_id"),
        group_id=opt_uuid(args, "group_id"),
        teacher_id=opt_uuid(args, "teacher_id"),
        room_id=opt_uuid(args, "room_id"),
    )
    return {"entries": to_jsonable(entries)}


async def list_lessons(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Lessons in a date range with optional filters."""
    filters = LessonFilters(
        start=opt_date(args, "from", "date_from"),
        end=opt_date(args, "to", "date_to"),
        group_id=opt_uuid(args, "group_id"),
        teacher_id=opt_uuid(args, "teacher_id"),
        room_id=opt_uuid(args, "room_id"),
        status=args.get("status") or None,
        teacher_needed=args.get("teacher_needed"),
    )
    page = await c.academic.schedule.list_lessons.execute(
        actor, filters, limit=MAX_LESSONS
    )
    return {"lessons": to_jsonable(page.items), "has_more": bool(page.next_cursor)}


async def attendance_stats(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Attendance statistics for a period."""
    view = str(args.get("view") or "group")
    if view not in ATTENDANCE_VIEWS:
        raise invalid("view must be group, student, subject or teacher")
    report = await c.academic.classwork.attendance_report.execute(
        actor,
        cast(AttendanceView, view),
        opt_date(args, "from", "date_from"),
        opt_date(args, "to", "date_to"),
        opt_uuid(args, "group_id"),
    )
    return to_jsonable_dict(report)


async def missing_attendance(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Finished lessons without submitted attendance."""
    start = opt_date(args, "from", "date_from")
    end = opt_date(args, "to", "date_to")
    if start is None or end is None:
        raise invalid("from and to are required")
    lessons = await c.academic.classwork.queries.missing_attendance(
        opt_uuid(args, "teacher_id"), start, end
    )
    return {"lessons": to_jsonable(lessons)}


async def list_broadcasts(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Broadcasts, optionally by status."""
    status = args.get("status")
    page = await c.admin.list_broadcasts.execute(
        actor,
        status=BroadcastStatus(status) if status else None,
        limit=limit_arg(args, 20, 50),
    )
    return to_jsonable_dict(page)


async def sync_status(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """The latest EMIS sync runs."""
    page = await c.academic.marks.list_sync_runs.execute(actor, None, 10)
    return {"runs": to_jsonable(page.items)}


async def audit_log(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Recent audit events, optionally filtered."""
    page = await c.identity.auth.list_audit.execute(
        user_id=opt_uuid(args, "user_id"),
        type=args.get("type") or None,
        since=day_start(opt_date(args, "from", "date_from")),
        until=day_end(opt_date(args, "to", "date_to")),
        cursor=None,
        limit=limit_arg(args, 20, 50),
    )
    events = [AuditItemResponse.of(event, page.actors) for event in page.items]
    return {"events": to_jsonable(events)}
