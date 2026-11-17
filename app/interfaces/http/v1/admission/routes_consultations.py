"""Consultation routes (`/v1/admission/consultations*`)."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.modules.admission.application.consultations import (
    ConsultationDraft,
    ConsultationView,
)
from app.modules.admission.domain.consultations import (
    DETAILS_MAX,
    LOCATION_MAX,
    MAX_TIMES,
    NOTES_MAX,
    TOPIC_MAX,
)

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

WithKindT = Literal["counselor", "mentor"]
LinkedKindT = Literal["project", "essay", "activity", "application", "other"]
FormatT = Literal["online", "offline"]
StatusT = Literal[
    "requested", "proposed", "accepted", "declined", "completed", "cancelled"
]


class ConsultationIn(BaseModel):
    """A new consultation request."""

    with_kind: WithKindT
    topic: str = Field(min_length=1, max_length=TOPIC_MAX)
    format: FormatT
    linked_kind: LinkedKindT = "other"
    linked_id: UUID | None = None
    details: str = Field(default="", max_length=DETAILS_MAX)
    preferred_times: list[dt.datetime] = Field(
        default_factory=list, max_length=MAX_TIMES
    )


class ConsultationSlotIn(BaseModel):
    """A time and a place offered by staff."""

    at: dt.datetime
    location: str = Field(default="", max_length=LOCATION_MAX)


class ConsultationAcceptIn(BaseModel):
    """Accept a request; `at` defaults to the first preferred time."""

    at: dt.datetime | None = None
    location: str = Field(default="", max_length=LOCATION_MAX)


class ConsultationDeclineIn(BaseModel):
    """Why the request is declined."""

    reason: str = Field(default="", max_length=NOTES_MAX)


class ConsultationCompleteIn(BaseModel):
    """Notes of a finished consultation."""

    notes: str = Field(default="", max_length=NOTES_MAX)


class ConsultationOut(BaseModel):
    """A consultation with the actions its viewer may take."""

    id: UUID
    student_id: UUID
    student_name: str
    with_kind: WithKindT
    topic: str
    linked_kind: LinkedKindT
    linked_id: UUID | None
    details: str
    preferred_times: list[dt.datetime]
    format: FormatT
    status: StatusT
    staff_id: UUID | None
    scheduled_at: dt.datetime | None
    location: str
    staff_notes: str
    decline_reason: str
    created_at: dt.datetime | None
    updated_at: dt.datetime | None
    completed_at: dt.datetime | None
    viewer: Literal["student", "staff"]
    actions: list[str]

    @classmethod
    def of(cls, v: ConsultationView) -> "ConsultationOut":
        """Map the view."""
        c = v.consultation
        return cls(
            id=c.id,
            student_id=c.student_id,
            student_name=v.student_name,
            with_kind=c.with_kind,
            topic=c.topic,
            linked_kind=c.linked_kind,
            linked_id=c.linked_id,
            details=c.details,
            preferred_times=list(c.preferred_times),
            format=c.format,
            status=c.status,
            staff_id=c.staff_id,
            scheduled_at=c.scheduled_at,
            location=c.location,
            staff_notes=c.staff_notes,
            decline_reason=c.decline_reason,
            created_at=c.created_at,
            updated_at=c.updated_at,
            completed_at=c.completed_at,
            viewer=v.viewer,
            actions=list(v.actions),
        )


class ConsultationListOut(BaseModel):
    """A list of consultations."""

    items: list[ConsultationOut]


def _list(views: list[ConsultationView]) -> ConsultationListOut:
    return ConsultationListOut(items=[ConsultationOut.of(v) for v in views])


async def request_consultation(
    body: ConsultationIn, container: ContainerDep, ctx: AdmissionCtx
) -> ConsultationOut:
    """Ask a counselor or a mentor for a consultation (at most 3 open)."""
    draft = ConsultationDraft(
        with_kind=body.with_kind,
        topic=body.topic,
        format=body.format,
        linked_kind=body.linked_kind,
        linked_id=body.linked_id,
        details=body.details,
        preferred_times=tuple(body.preferred_times),
    )
    return ConsultationOut.of(
        await container.admission.consultations.request(ctx, draft)
    )


async def my_consultations(
    container: ContainerDep, ctx: AdmissionCtx
) -> ConsultationListOut:
    """My consultation requests, newest first."""
    return _list(await container.admission.consultations.mine(ctx))


async def consultation_queue(
    container: ContainerDep,
    ctx: AdmissionCtx,
    status: list[StatusT] | None = Query(default=None),
) -> ConsultationListOut:
    """Staff: open requests of my kind plus the ones I answer."""
    wanted = tuple(status) if status else None
    return _list(await container.admission.consultations.queue(ctx, wanted))


async def confirm_consultation(
    consultation_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ConsultationOut:
    """Student: accept the time staff proposed."""
    return ConsultationOut.of(
        await container.admission.consultations.confirm(ctx, consultation_id)
    )


async def reject_consultation(
    consultation_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ConsultationOut:
    """Student: turn the proposed time down; the request returns to the queue."""
    return ConsultationOut.of(
        await container.admission.consultations.reject(ctx, consultation_id)
    )


async def cancel_consultation(
    consultation_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ConsultationOut:
    """Withdraw a consultation (the student or the answering staff member)."""
    return ConsultationOut.of(
        await container.admission.consultations.cancel(ctx, consultation_id)
    )


async def accept_consultation(
    consultation_id: UUID,
    body: ConsultationAcceptIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> ConsultationOut:
    """Staff: take the request."""
    return ConsultationOut.of(
        await container.admission.consultations.accept(
            ctx, consultation_id, body.at, body.location
        )
    )


async def propose_consultation(
    consultation_id: UUID,
    body: ConsultationSlotIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> ConsultationOut:
    """Staff: offer another time; the student confirms or rejects."""
    return ConsultationOut.of(
        await container.admission.consultations.propose(
            ctx, consultation_id, body.at, body.location
        )
    )


async def decline_consultation(
    consultation_id: UUID,
    body: ConsultationDeclineIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> ConsultationOut:
    """Staff: decline the request."""
    return ConsultationOut.of(
        await container.admission.consultations.decline(
            ctx, consultation_id, body.reason
        )
    )


async def complete_consultation(
    consultation_id: UUID,
    body: ConsultationCompleteIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> ConsultationOut:
    """Staff: close an accepted consultation with notes."""
    return ConsultationOut.of(
        await container.admission.consultations.complete(
            ctx, consultation_id, body.notes
        )
    )


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path,
        endpoint,
        methods=[method],
        operation_id=f"admission_{op}",
        response_model=kw.pop("response_model", ConsultationOut),
        **kw,
    )


_route(
    "/consultations",
    request_consultation,
    "POST",
    "consultations_request",
    status_code=201,
)
_route(
    "/consultations",
    my_consultations,
    "GET",
    "consultations_mine",
    response_model=ConsultationListOut,
)
_route(
    "/consultations/queue",
    consultation_queue,
    "GET",
    "consultations_queue",
    response_model=ConsultationListOut,
)
_route(
    "/consultations/{consultation_id}/confirm",
    confirm_consultation,
    "POST",
    "consultations_confirm",
)
_route(
    "/consultations/{consultation_id}/reject",
    reject_consultation,
    "POST",
    "consultations_reject",
)
_route(
    "/consultations/{consultation_id}/cancel",
    cancel_consultation,
    "POST",
    "consultations_cancel",
)
_route(
    "/consultations/{consultation_id}/accept",
    accept_consultation,
    "POST",
    "consultations_accept",
)
_route(
    "/consultations/{consultation_id}/propose",
    propose_consultation,
    "POST",
    "consultations_propose",
)
_route(
    "/consultations/{consultation_id}/decline",
    decline_consultation,
    "POST",
    "consultations_decline",
)
_route(
    "/consultations/{consultation_id}/complete",
    complete_consultation,
    "POST",
    "consultations_complete",
)
