"""Write Administration tools: the same use cases as the Administration routes."""

from typing import Any

from app.bootstrap.adapters.admin_tools_args import Args, uuid_arg, validate
from app.bootstrap.container import Container
from app.interfaces.http.v1.admin_broadcasts.schemas import BroadcastInputBody
from app.interfaces.http.v1.admin_schedule.groups.schemas import (
    GroupCreateBody,
    GroupItemResponse,
    GroupPatchBody,
)
from app.interfaces.http.v1.admin_schedule.lessons.schemas import (
    ExtraLessonInputBody,
    LessonPatchBody,
)
from app.interfaces.http.v1.admin_schedule.shared_schemas import LessonItemResponse
from app.interfaces.http.v1.admin_schedule.timetable.inputs import (
    to_entry_input,
    to_entry_patch,
)
from app.interfaces.http.v1.admin_schedule.timetable.schemas import (
    TimetableEntryInputBody,
    TimetableEntryPatchBody,
    TimetableEntryResponse,
)
from app.interfaces.http.v1.admin_users.teachers.schemas import (
    TeacherCreateBody,
    TeacherPatchBody,
)
from app.interfaces.mcp.jsonable import to_jsonable_dict
from app.modules.academic.application.schedule.create_extra_lesson import (
    ExtraLessonInput,
)
from app.modules.academic.application.schedule.unset import UNSET
from app.modules.academic.application.schedule.update_lesson import LessonPatch
from app.modules.admin.domain.broadcast import CreatedVia
from app.modules.identity.application.request_context import RequestContext
from app.shared.actor import Actor


def _without(args: Args, *names: str) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key not in names}


async def create_teacher(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Create a teacher account; the result holds the activation link."""
    body = validate(TeacherCreateBody, args)
    created = await c.identity.auth.create_teacher.execute(
        actor.user_id,
        last_name=body.last_name,
        first_name=body.first_name,
        middle_name=body.middle_name,
        email=str(body.email),
        ctx=RequestContext(),
    )
    return {
        "teacher_id": str(created.user.id),
        "login": created.user.login,
        "activation_url": created.activation_url,
    }


async def update_teacher(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Edit a teacher's names or (before activation) email."""
    body = validate(TeacherPatchBody, _without(args, "teacher_id"))
    user = await c.identity.auth.update_teacher.execute(
        actor,
        uuid_arg(args, "teacher_id"),
        last_name=body.last_name,
        first_name=body.first_name,
        middle_name=body.middle_name,
        email=str(body.email) if body.email else None,
        ctx=RequestContext(),
    )
    return {"teacher_id": str(user.id), "updated": True}


async def create_group(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Create a group."""
    body = validate(GroupCreateBody, args)
    group = await c.academic.schedule.create_group.execute(
        name=body.name,
        emis_group_id=body.emis_group_id,
        current_semester=body.current_semester,
    )
    return to_jsonable_dict(GroupItemResponse.model_validate(group))


async def update_group(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Set a group's curator, head student or status; null clears curator or head."""
    body = validate(GroupPatchBody, _without(args, "group_id"))
    sent = body.model_fields_set
    detail = await c.academic.schedule.update_group.execute(
        actor,
        uuid_arg(args, "group_id"),
        curator_id=body.curator_id if "curator_id" in sent else UNSET,
        head_student_id=body.head_student_id if "head_student_id" in sent else UNSET,
        status=body.status,
    )
    return to_jsonable_dict(detail)


async def create_timetable_entry(
    c: Container, args: Args, actor: Actor
) -> dict[str, Any]:
    """Add a weekly timetable entry (a conflict is reported as an error)."""
    body = validate(TimetableEntryInputBody, args)
    entry = await c.academic.schedule.create_entry.execute(actor, to_entry_input(body))
    return to_jsonable_dict(TimetableEntryResponse.model_validate(entry))


async def update_timetable_entry(
    c: Container, args: Args, actor: Actor
) -> dict[str, Any]:
    """Change the sent fields of a timetable entry."""
    body = validate(TimetableEntryPatchBody, _without(args, "entry_id"))
    entry = await c.academic.schedule.update_entry.execute(
        actor, uuid_arg(args, "entry_id"), to_entry_patch(body)
    )
    return to_jsonable_dict(TimetableEntryResponse.model_validate(entry))


async def delete_timetable_entry(
    c: Container, args: Args, actor: Actor
) -> dict[str, Any]:
    """Delete a timetable entry."""
    await c.academic.schedule.delete_entry.execute(uuid_arg(args, "entry_id"))
    return {"deleted": True}


async def create_lesson(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Add a one-off lesson."""
    body = validate(ExtraLessonInputBody, args)
    item = await c.academic.schedule.create_extra_lesson.execute(
        actor,
        ExtraLessonInput(
            date=body.date,
            period=body.period,
            subject_id=body.subject_id,
            teacher_id=body.teacher_id,
            room_name=body.room_name,
            audience=[(a.group_id, a.subgroup) for a in body.audience],
            topic=body.topic,
        ),
    )
    return to_jsonable_dict(LessonItemResponse.model_validate(item))


async def update_lesson(c: Container, args: Args, actor: Actor) -> dict[str, Any]:
    """Cancel, move or replace one lesson; only the sent fields change."""
    body = validate(LessonPatchBody, _without(args, "lesson_id"))
    sent = body.model_fields_set
    patch = LessonPatch(
        status=body.status,
        teacher_id=body.teacher_id if "teacher_id" in sent else UNSET,
        subject_id=body.subject_id,
        room_name=body.room_name if "room_name" in sent else UNSET,
        date=body.date,
        period=body.period,
        topic=body.topic if "topic" in sent else UNSET,
    )
    item = await c.academic.schedule.update_lesson.execute(
        actor, uuid_arg(args, "lesson_id"), patch
    )
    return to_jsonable_dict(LessonItemResponse.model_validate(item))


async def create_broadcast_draft(
    c: Container, args: Args, actor: Actor
) -> dict[str, Any]:
    """Create a broadcast draft; a person reviews and sends it in the admin UI."""
    body = validate(BroadcastInputBody, args)
    view = await c.admin.create_broadcast.execute(
        actor,
        title=body.title,
        text=body.text,
        media_file_ids=body.media_file_ids,
        audience=body.audience.to_domain(),
        created_via=CreatedVia.ASSISTANT,
    )
    return to_jsonable_dict(view)
