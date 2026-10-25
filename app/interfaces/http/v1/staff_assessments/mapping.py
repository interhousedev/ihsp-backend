"""Turns request bodies and queries into assessment use case inputs."""

import datetime as dt
from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.me_assessments.schemas import (
    AssessmentCreateBody,
    AssessmentKind,
    AssessmentPatchBody,
    AssessmentSource,
    AssessmentStatus,
)
from app.modules.academic.application.assessments.inputs import (
    AssessmentInput,
    StaffFilters,
)
from app.modules.academic.domain.assessments.edit import UNSET, AssessmentPatch

from fastapi import Query


def to_input(body: AssessmentCreateBody) -> AssessmentInput:
    """Map the create body."""
    return AssessmentInput(
        subject_id=body.subject_id,
        audience=[(a.group_id, a.subgroup) for a in body.audience],
        kind=body.kind,
        date=body.date,
        title=body.title,
        starts_at=body.starts_at,
        room=body.room,
        note=body.note,
        lesson_id=body.lesson_id,
        control=body.control,
    )


def to_patch(body: AssessmentPatchBody) -> AssessmentPatch:
    """Map the patch body.

    Fields that cannot be cleared are set when not null; the optional ones (start
    time, room, note, lesson, control) are set whenever the client sent them, even as
    null.
    """
    sent = body.model_fields_set
    audience = (
        UNSET
        if body.audience is None
        else [(a.group_id, a.subgroup) for a in body.audience]
    )
    return AssessmentPatch(
        subject_id=UNSET if body.subject_id is None else body.subject_id,
        audience=audience,
        kind=UNSET if body.kind is None else body.kind,
        title=UNSET if body.title is None else body.title,
        date=UNSET if body.date is None else body.date,
        starts_at=body.starts_at if "starts_at" in sent else UNSET,
        room=body.room if "room" in sent else UNSET,
        note=body.note if "note" in sent else UNSET,
        lesson_id=body.lesson_id if "lesson_id" in sent else UNSET,
        control=body.control if "control" in sent else UNSET,
        status=UNSET if body.status is None else body.status,
    )


def filters(
    since: Annotated[dt.date | None, Query(alias="from")] = None,
    until: Annotated[dt.date | None, Query(alias="to")] = None,
    subject_id: UUID | None = None,
    group_id: UUID | None = None,
    kind: AssessmentKind | None = None,
    status: AssessmentStatus | None = None,
    source: AssessmentSource | None = None,
    undated: Annotated[
        bool, Query(description="Also list control weeks without a subject date.")
    ] = False,
) -> StaffFilters:
    """Query parameters of the staff and admin listings."""
    return StaffFilters(
        since=since,
        until=until,
        subject_id=subject_id,
        group_id=group_id,
        kind=kind,
        status=status,
        source=source,
        undated=undated,
    )
