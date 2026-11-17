"""Request and response models of `/v1/admission/*`."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.admission.application.config import (
    AdmissionConfig,
    AdmissionMe,
    WorkflowOptions,
)
from app.modules.admission.domain.courses import Course

from pydantic import BaseModel, Field


class QuestionOut(BaseModel):
    """A wizard question; the web holds the texts by `id`."""

    id: str
    section: str
    kind: str
    required: bool
    options: list[str]
    max_length: int | None
    max_choices: int | None
    visible_if: str | None
    prefill_source: str | None
    sensitivity: str
    visible_to: str


class SubRoleOut(BaseModel):
    """A built-in staff sub-role."""

    key: str
    kind: str
    names: dict[str, str]
    permissions: list[str]


class DocumentKindOptionOut(BaseModel):
    """A document kind id; confidential kinds need the confidential permission."""

    id: str
    confidential: bool


class RoundOptionOut(BaseModel):
    """An application round id; a binding round needs a resolved affordability."""

    id: str
    binding: bool


class WorkflowOptionsOut(BaseModel):
    """Ids of the document, deadline, list and plan vocabularies; texts are web-side."""

    document_kinds: list[DocumentKindOptionOut]
    reject_reasons: list[str]
    reminder_offsets: list[int]
    reminder_channels: list[str]
    deadline_statuses: list[str]
    rounds: list[RoundOptionOut]
    list_statuses: list[str]
    buckets: list[str]
    milestone_kinds: list[str]
    milestone_statuses: list[str]
    affordability_statuses: list[str]
    affordability_ack_statuses: list[str]
    task_statuses: list[str]
    task_priorities: list[str]
    task_sources: list[str]
    task_link_kinds: list[str]
    task_horizons: list[str]

    @classmethod
    def of(cls, w: WorkflowOptions) -> "WorkflowOptionsOut":
        """Map the domain vocabularies."""
        return cls(
            document_kinds=[
                DocumentKindOptionOut(id=i, confidential=c) for i, c in w.document_kinds
            ],
            reject_reasons=list(w.reject_reasons),
            reminder_offsets=list(w.reminder_offsets),
            reminder_channels=list(w.reminder_channels),
            deadline_statuses=list(w.deadline_statuses),
            rounds=[RoundOptionOut(id=i, binding=b) for i, b in w.rounds],
            list_statuses=list(w.list_statuses),
            buckets=list(w.buckets),
            milestone_kinds=list(w.milestone_kinds),
            milestone_statuses=list(w.milestone_statuses),
            affordability_statuses=list(w.affordability_statuses),
            affordability_ack_statuses=list(w.affordability_ack_statuses),
            task_statuses=list(w.task_statuses),
            task_priorities=list(w.task_priorities),
            task_sources=list(w.task_sources),
            task_link_kinds=list(w.task_link_kinds),
            task_horizons=list(w.task_horizons),
        )


class AdmissionConfigOut(BaseModel):
    """Public configuration of the admission app."""

    question_set: str
    questions: list[QuestionOut]
    options: dict[str, list[str]]
    stages: list[str]
    limits: dict[str, int]
    estimates_student_visible: bool
    wellbeing_questions_enabled: bool
    sub_roles: list[SubRoleOut]
    pickup_location: dict[str, str] | None
    item_caps: dict[str, int]
    workflow: WorkflowOptionsOut

    @classmethod
    def of(cls, cfg: AdmissionConfig) -> "AdmissionConfigOut":
        """Map the use-case result."""
        return cls(
            question_set=cfg.question_set,
            questions=[
                QuestionOut(
                    id=q.id,
                    section=q.section,
                    kind=q.kind,
                    required=q.required,
                    options=list(q.options),
                    max_length=q.max_length,
                    max_choices=q.max_choices,
                    visible_if=q.visible_if,
                    prefill_source=q.prefill_source,
                    sensitivity=q.sensitivity,
                    visible_to=q.visible_to,
                )
                for q in cfg.questions
                if q.enabled
            ],
            options={k: list(v) for k, v in cfg.options.items()},
            stages=list(cfg.stages),
            limits=cfg.limits,
            estimates_student_visible=cfg.estimates_student_visible,
            wellbeing_questions_enabled=cfg.wellbeing_questions_enabled,
            sub_roles=[
                SubRoleOut(
                    key=r.key,
                    kind=r.kind,
                    names=dict(zip(("uz", "ru", "en"), r.names, strict=True)),
                    permissions=sorted(str(p) for p in r.permissions),
                )
                for r in cfg.sub_roles
            ],
            pickup_location=cfg.pickup_location,
            item_caps=cfg.item_caps,
            workflow=WorkflowOptionsOut.of(cfg.workflow),
        )


class AssignmentOut(BaseModel):
    """A staff sub-role assignment in force."""

    assignment_id: UUID
    role_id: UUID
    kind: str
    name: str
    name_i18n: dict[str, str] | None
    scope_kind: str
    scope_ref: str | None
    expires_at: datetime | None


class AdmissionMeOut(BaseModel):
    """The caller's standing in the admission app."""

    kind: Literal["applicant", "staff", "none"]
    may_enter: bool
    ineligible_reason: str | None
    grade: int | None
    entitlement_kind: str | None
    staff_roles: list[str]
    sub_roles: list[AssignmentOut]

    @classmethod
    def of(cls, me: AdmissionMe) -> "AdmissionMeOut":
        """Map the use-case result."""
        subs: list[dict[str, Any]] = [dict(s) for s in me.sub_roles]
        for s in subs:
            s["scope_ref"] = None if s["scope_ref"] is None else str(s["scope_ref"])
        return cls(
            kind=me.kind,
            may_enter=me.may_enter,
            ineligible_reason=me.ineligible_reason,
            grade=me.grade,
            entitlement_kind=me.entitlement_kind,
            staff_roles=list(me.staff_roles),
            sub_roles=[AssignmentOut(**s) for s in subs],
        )


class CourseOut(BaseModel):
    """A course on the student's profile."""

    id: UUID | None
    source: str
    source_ref: str | None
    title: str
    provider: str | None
    level: str | None
    year: int | None
    grade: str | None
    included: bool

    @classmethod
    def of(cls, c: Course) -> "CourseOut":
        """Map a domain course."""
        return cls(
            id=c.id,
            source=c.source,
            source_ref=c.source_ref,
            title=c.title,
            provider=c.provider,
            level=c.level,
            year=c.year,
            grade=c.grade,
            included=c.included,
        )


class CourseListOut(BaseModel):
    """Merged academic, LMS and manual courses."""

    items: list[CourseOut]


class ManualCourseIn(BaseModel):
    """A course taken outside the lyceum."""

    title: str = Field(min_length=1, max_length=200)
    provider: str | None = Field(default=None, max_length=200)
    level: str | None = Field(default=None, max_length=50)
    year: int | None = Field(default=None, ge=1990, le=2100)
    grade: str | None = Field(default=None, max_length=20)


class CourseIncludedIn(BaseModel):
    """Include or exclude a course from the profile."""

    included: bool
