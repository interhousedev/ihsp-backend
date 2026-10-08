"""Mapping timetable request bodies to application inputs."""

from app.interfaces.http.v1.admin_schedule.timetable.schemas import (
    TimetableEntryInputBody,
    TimetableEntryPatchBody,
)
from app.modules.academic.application.schedule.entry_builder import EntryInput
from app.modules.academic.application.schedule.unset import UNSET
from app.modules.academic.application.schedule.update_entry import EntryPatch


def to_entry_input(body: TimetableEntryInputBody) -> EntryInput:
    """Build the application input of a create or check request."""
    return EntryInput(
        term_id=body.term_id,
        weekday=body.weekday,
        period=body.period,
        week_parity=body.week_parity,
        subject_id=body.subject_id,
        teacher_id=body.teacher_id,
        room_name=body.room_name,
        audience=[(item.group_id, item.subgroup) for item in body.audience],
        valid_from=body.valid_from,
        valid_to=body.valid_to,
    )


def to_entry_patch(body: TimetableEntryPatchBody) -> EntryPatch:
    """Build a patch where only the fields that were sent are applied."""
    sent = body.model_fields_set
    return EntryPatch(
        term_id=body.term_id,
        weekday=body.weekday,
        period=body.period,
        week_parity=body.week_parity,
        subject_id=body.subject_id,
        teacher_id=body.teacher_id if "teacher_id" in sent else UNSET,
        room_name=body.room_name if "room_name" in sent else UNSET,
        audience=(
            [(item.group_id, item.subgroup) for item in body.audience]
            if body.audience is not None
            else None
        ),
        valid_from=body.valid_from,
        valid_to=body.valid_to if "valid_to" in sent else UNSET,
    )
