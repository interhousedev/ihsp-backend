"""Schemas of the opportunities catalog and plans (`/v1/admission/opportunities`)."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admission.schemas_opp_comments import OppCommentOut
from app.interfaces.http.v1.admission.schemas_orgs import OrgOut
from app.modules.admission.application.opportunities import (
    OpportunityDeadline,
    PlanView,
    TaxonomyField,
)
from app.modules.admission.application.opportunity_planner import AiPlan
from app.modules.admission.domain.opportunities import (
    DatedEvent,
    Opportunity,
    OpportunityDraft,
    OpportunityMaterial,
    OpportunitySubmission,
    PlanEntry,
    TaxonomyNode,
)
from app.modules.admission.domain.orgs import Organization

from pydantic import BaseModel, Field

Kind = Literal[
    "exam",
    "certification",
    "course",
    "event",
    "recurring",
    "program",
    "scholarship",
    "research",
]
AwardType = Literal["scholarship", "fellowship", "grant", "tuition_waiver", "program"]
Coverage = Literal["full_tuition", "partial_tuition", "stipend", "cash", "travel"]
Scope = Literal["local", "international"]
CollegeCredit = Literal["none", "possible", "yes"]
Sort = Literal["title", "ranking", "acceptance", "tuition", "relevance", "deadline"]
MaterialKind = Literal["link", "lms_course", "alumni", "center"]
Status = Literal["pending", "approved", "rejected"]
Level = Literal["field", "subfield", "subject"]


class TaxonomySubjectOut(BaseModel):
    """A subject."""

    id: UUID
    name: dict[str, str]


class TaxonomySubfieldOut(BaseModel):
    """A subfield with its subjects."""

    id: UUID
    name: dict[str, str]
    subjects: list[TaxonomySubjectOut]


class TaxonomyFieldOut(BaseModel):
    """A field with its subfields."""

    id: UUID
    name: dict[str, str]
    subfields: list[TaxonomySubfieldOut]

    @classmethod
    def of(cls, f: TaxonomyField) -> "TaxonomyFieldOut":
        """Map a field."""
        return cls(
            id=f.id,
            name=f.name,
            subfields=[
                TaxonomySubfieldOut(
                    id=s.id,
                    name=s.name,
                    subjects=[
                        TaxonomySubjectOut(id=j.id, name=j.name) for j in s.subjects
                    ],
                )
                for s in f.subfields
            ],
        )


class TaxonomyOut(BaseModel):
    """The whole taxonomy and whether the caller may edit it."""

    fields: list[TaxonomyFieldOut]
    can_moderate: bool


class TaxonomyNodeIn(BaseModel):
    """Create a node."""

    level: Level
    parent_id: UUID | None = None
    names: dict[str, str]
    position: int = Field(default=0, ge=0, le=10000)


class TaxonomyNodeOut(BaseModel):
    """A stored node."""

    id: UUID
    level: Level
    parent_id: UUID | None
    names: dict[str, str]
    position: int

    @classmethod
    def of(cls, n: TaxonomyNode) -> "TaxonomyNodeOut":
        """Map a node."""
        return cls(
            id=n.id,
            level=n.level,
            parent_id=n.parent_id,
            names=n.names,
            position=n.position,
        )


class MaterialIo(BaseModel):
    """A way to prepare."""

    kind: MaterialKind
    title: str = Field(max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=1000)
    lms_course_id: UUID | None = None


class OpportunityFields(BaseModel):
    """The editable fields of an entry."""

    kind: Kind
    title: str = Field(max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    url: str | None = Field(default=None, max_length=2000)
    provider: str | None = Field(default=None, max_length=300)
    subject_ids: list[UUID] = Field(default_factory=list, max_length=10)
    grades: list[int] = Field(default_factory=list, max_length=4)
    registration_deadlines: list[dt.date] = Field(default_factory=list, max_length=12)
    exam_dates: list[dt.date] = Field(default_factory=list, max_length=12)
    last_year_dates: list[dt.date] = Field(default_factory=list, max_length=12)
    recurrence: str | None = Field(default=None, max_length=200)
    lms_course_id: UUID | None = None
    materials: list[MaterialIo] = Field(default_factory=list, max_length=20)
    country: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    online: bool = False
    acceptance_rate: float | None = Field(default=None, ge=0, le=100)
    tuition_usd: int | None = Field(default=None, ge=0)
    logo_url: str | None = Field(default=None, max_length=2000)
    host_institution: str | None = Field(default=None, max_length=300)
    duration_weeks: int | None = Field(default=None, ge=1)
    ranking: int | None = Field(default=None, ge=1)
    org_id: UUID | None = None
    award_type: AwardType | None = None
    coverage: list[Coverage] = Field(default_factory=list, max_length=5)
    scope: Scope | None = None
    amount_text: str | None = Field(default=None, max_length=300)
    amount_value: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    essay_required: bool = False
    eligibility: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=2000)
    college_credit: CollegeCredit | None = None
    credit_note: str | None = Field(default=None, max_length=300)
    study_field_ids: list[str] = Field(default_factory=list, max_length=8)

    def draft(self, note: str | None) -> OpportunityDraft:
        """The domain draft."""
        return OpportunityDraft(
            kind=self.kind,
            title=self.title,
            summary=self.summary,
            url=self.url,
            provider=self.provider,
            subject_ids=tuple(self.subject_ids),
            grades=tuple(self.grades),
            registration_deadlines=tuple(self.registration_deadlines),
            exam_dates=tuple(self.exam_dates),
            last_year_dates=tuple(self.last_year_dates),
            recurrence=self.recurrence,
            lms_course_id=self.lms_course_id,
            materials=tuple(
                OpportunityMaterial(
                    kind=m.kind,
                    title=m.title,
                    url=m.url,
                    note=m.note,
                    lms_course_id=m.lms_course_id,
                )
                for m in self.materials
            ),
            note=note,
            country=self.country,
            location=self.location,
            online=self.online,
            acceptance_rate=self.acceptance_rate,
            tuition_usd=self.tuition_usd,
            logo_url=self.logo_url,
            host_institution=self.host_institution,
            duration_weeks=self.duration_weeks,
            ranking=self.ranking,
            org_id=self.org_id,
            award_type=self.award_type,
            coverage=tuple(self.coverage),
            scope=self.scope,
            amount_text=self.amount_text,
            amount_value=self.amount_value,
            currency=self.currency,
            essay_required=self.essay_required,
            eligibility=self.eligibility,
            source_url=self.source_url,
            college_credit=self.college_credit,
            credit_note=self.credit_note,
            study_field_ids=tuple(self.study_field_ids),
        )

    @classmethod
    def of_draft(cls, d: OpportunityDraft) -> "OpportunityFields":
        """Map a draft."""
        return cls(
            kind=d.kind,
            title=d.title,
            summary=d.summary,
            url=d.url,
            provider=d.provider,
            subject_ids=list(d.subject_ids),
            grades=list(d.grades),
            registration_deadlines=list(d.registration_deadlines),
            exam_dates=list(d.exam_dates),
            last_year_dates=list(d.last_year_dates),
            recurrence=d.recurrence,
            lms_course_id=d.lms_course_id,
            materials=[
                MaterialIo(
                    kind=m.kind,
                    title=m.title,
                    url=m.url,
                    note=m.note,
                    lms_course_id=m.lms_course_id,
                )
                for m in d.materials
            ],
            country=d.country,
            location=d.location,
            online=d.online,
            acceptance_rate=d.acceptance_rate,
            tuition_usd=d.tuition_usd,
            logo_url=d.logo_url,
            host_institution=d.host_institution,
            duration_weeks=d.duration_weeks,
            ranking=d.ranking,
            org_id=d.org_id,
            award_type=d.award_type,
            coverage=list(d.coverage),
            scope=d.scope,
            amount_text=d.amount_text,
            amount_value=d.amount_value,
            currency=d.currency,
            essay_required=d.essay_required,
            eligibility=d.eligibility,
            source_url=d.source_url,
            college_credit=d.college_credit,
            credit_note=d.credit_note,
            study_field_ids=list(d.study_field_ids),
        )


class SubmissionIn(BaseModel):
    """Propose a new entry, or an edit of `target_id`."""

    target_id: UUID | None = None
    fields: OpportunityFields
    note: str | None = Field(default=None, max_length=1000)


class ReviewIn(BaseModel):
    """Approve or reject (a rejection needs a reason)."""

    approve: bool
    reason: str | None = Field(default=None, max_length=500)
    lock_version: int


class ArchiveIn(BaseModel):
    """Hide or restore an entry."""

    archived: bool


class SubmissionOut(BaseModel):
    """A stored submission."""

    id: UUID
    target_id: UUID | None
    fields: OpportunityFields
    note: str | None
    status: Status
    submitted_by: UUID
    submitter_role: Literal["student", "staff", "helper", "admin"]
    created_at: dt.datetime
    reviewed_by: UUID | None
    reviewed_at: dt.datetime | None
    reason: str | None
    applied_id: UUID | None
    lock_version: int

    @classmethod
    def of(cls, s: OpportunitySubmission) -> "SubmissionOut":
        """Map a submission."""
        return cls(
            id=s.id,
            target_id=s.target_id,
            fields=OpportunityFields.of_draft(OpportunityDraft.from_payload(s.payload)),
            note=s.note,
            status=s.status,
            submitted_by=s.submitted_by,
            submitter_role=s.submitter_role,
            created_at=s.created_at,
            reviewed_by=s.reviewed_by,
            reviewed_at=s.reviewed_at,
            reason=s.reason,
            applied_id=s.applied_id,
            lock_version=s.lock_version,
        )


class SubmissionListOut(BaseModel):
    """Submissions and whether the caller moderates."""

    items: list[SubmissionOut]
    can_moderate: bool


class DatedEventOut(BaseModel):
    """A date; `projected` when expected from last year or a recurrence."""

    day: dt.date
    kind: str
    projected: bool

    @classmethod
    def of(cls, e: DatedEvent) -> "DatedEventOut":
        """Map an event."""
        return cls(day=e.day, kind=e.kind, projected=e.projected)


class OpportunityOut(BaseModel):
    """A published entry with its next dates."""

    id: UUID
    fields: OpportunityFields
    archived: bool
    created_at: dt.datetime
    updated_at: dt.datetime
    lock_version: int
    upcoming: list[DatedEventOut]
    next_deadline: dt.date | None
    org: OrgOut | None = None
    comment_count: int = 0
    for_you: bool = False

    @classmethod
    def of(
        cls,
        o: Opportunity,
        upcoming: list[DatedEvent],
        next_deadline: dt.date | None,
        org: Organization | None = None,
        comment_count: int = 0,
        for_you: bool = False,
    ) -> "OpportunityOut":
        """Map an entry."""
        return cls(
            id=o.id,
            fields=OpportunityFields.of_draft(o.draft),
            archived=o.archived,
            created_at=o.created_at,
            updated_at=o.updated_at,
            lock_version=o.lock_version,
            upcoming=[DatedEventOut.of(e) for e in upcoming],
            next_deadline=next_deadline,
            org=OrgOut.of(org) if org else None,
            comment_count=comment_count,
            for_you=for_you,
        )


class OpportunityDetailOut(OpportunityOut):
    """An entry with its organization and published comments."""

    comments: list[OppCommentOut] = Field(default_factory=list)
    can_moderate: bool = False


class OpportunityListOut(BaseModel):
    """One page of filtered entries; `total` counts all matches."""

    items: list[OpportunityOut]
    total: int
    page: int
    size: int
    sort: Sort


class PlanEntryIn(BaseModel):
    """Save an entry to the plan, optionally placed in a grade."""

    planned_grade: int | None = Field(default=None, ge=9, le=12)
    note: str | None = Field(default=None, max_length=500)


class PlanEntryOut(BaseModel):
    """A saved entry."""

    id: UUID
    opportunity_id: UUID
    planned_grade: int | None
    note: str | None
    created_at: dt.datetime

    @classmethod
    def of(cls, e: PlanEntry) -> "PlanEntryOut":
        """Map an entry."""
        return cls(
            id=e.id,
            opportunity_id=e.opportunity_id,
            planned_grade=e.planned_grade,
            note=e.note,
            created_at=e.created_at,
        )


class DeadlineOut(BaseModel):
    """A dated event of a saved entry."""

    opportunity_id: UUID
    title: str
    day: dt.date
    kind: str
    projected: bool

    @classmethod
    def of(cls, d: OpportunityDeadline) -> "DeadlineOut":
        """Map a deadline."""
        return cls(
            opportunity_id=d.opportunity_id,
            title=d.title,
            day=d.day,
            kind=d.kind,
            projected=d.projected,
        )


class ConflictOut(BaseModel):
    """Two saved entries on the same day."""

    first_id: UUID
    second_id: UUID
    day: dt.date


class AnalyticsOut(BaseModel):
    """Load per `grade:term` ("10:fall"; fall/spring/summer/any), coverage by field."""

    load: dict[str, int]
    coverage: dict[str, int]
    unplaced: int
    conflicts: list[ConflictOut]


class PlanOut(BaseModel):
    """A student's plan."""

    entries: list[PlanEntryOut]
    opportunities: list[OpportunityOut]
    analytics: AnalyticsOut
    deadlines: list[DeadlineOut]

    @classmethod
    def of(cls, v: PlanView) -> "PlanOut":
        """Map a plan view."""
        a = v.analytics
        return cls(
            entries=[PlanEntryOut.of(e) for e in v.entries],
            opportunities=[OpportunityOut.of(o, [], None) for o in v.catalog.values()],
            analytics=AnalyticsOut(
                load=a.load,
                coverage={str(k): n for k, n in a.coverage.items()},
                unplaced=a.unplaced,
                conflicts=[
                    ConflictOut(first_id=x, second_id=y, day=d)
                    for x, y, d in a.conflicts
                ],
            ),
            deadlines=[DeadlineOut.of(d) for d in v.deadlines],
        )


class DeadlineListOut(BaseModel):
    """Dated events in a window."""

    items: list[DeadlineOut]


class AiPlanIn(BaseModel):
    """What the student adds for the planner."""

    locale: Literal["uz", "ru", "en"] = "ru"
    interests: str = Field(default="", max_length=500)
    career: str = Field(default="", max_length=300)


class AiStepOut(BaseModel):
    """A saved entry placed in a grade and term."""

    opportunity_id: UUID
    grade: int
    term: str
    why: str


class AiConflictOut(BaseModel):
    """Two entries that clash."""

    first_id: UUID
    second_id: UUID
    reason: str


class AiDeadlineOut(BaseModel):
    """A deadline not to miss."""

    opportunity_id: UUID
    note: str


class AiPlanOut(BaseModel):
    """The generated plan; `plan` is null before the first run."""

    steps: list[AiStepOut]
    conflicts: list[AiConflictOut]
    deadlines: list[AiDeadlineOut]
    notes: list[str]
    created_at: dt.datetime

    @classmethod
    def of(cls, p: AiPlan) -> "AiPlanOut":
        """Map a plan."""
        return cls(
            steps=[
                AiStepOut(
                    opportunity_id=s.opportunity_id,
                    grade=s.grade,
                    term=s.term,
                    why=s.why,
                )
                for s in p.steps
            ],
            conflicts=[
                AiConflictOut(
                    first_id=c.first_id, second_id=c.second_id, reason=c.reason
                )
                for c in p.conflicts
            ],
            deadlines=[
                AiDeadlineOut(opportunity_id=d.opportunity_id, note=d.note)
                for d in p.deadlines
            ],
            notes=list(p.notes),
            created_at=p.created_at,
        )


class AiPlanEnvelope(BaseModel):
    """The last generated plan, if any."""

    plan: AiPlanOut | None
