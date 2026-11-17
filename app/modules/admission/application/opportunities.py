"""Opportunities: taxonomy, submissions with moderation, browsing and plans."""

import dataclasses
import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidProofUrlError,
    InvalidTransitionError,
    ItemLimitError,
)
from app.modules.admission.domain.opportunities import (
    GRADES,
    LOCALES,
    MAX_PLAN_ITEMS,
    NAME_MAX,
    PARENT_LEVEL,
    REASON_MAX,
    DatedEvent,
    Opportunity,
    OpportunityDraft,
    OpportunitySubmission,
    PlanAnalytics,
    PlanEntry,
    SubmitterRole,
    TaxonomyLevel,
    TaxonomyNode,
    analyse,
    review_transition,
    upcoming_dates,
)
from app.modules.admission.domain.permissions import KIND_ROLE, Permission
from app.modules.admission.ports.opportunities import OpportunityUnitOfWork
from app.modules.admission.ports.repositories import AuditEvent
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

OppUowFactory = Callable[[], OpportunityUnitOfWork]
HORIZON_DAYS = 4 * 366
STUDENT_SUBMIT_LIMIT = 5  # student submissions per day (spam guard)
_DAY = 86400


class LmsCourseLookup(Protocol):
    """Port: the title of a local LMS course (None when it does not exist)."""

    async def course_title(self, course_id: UUID) -> str | None:
        """Return the course title."""
        ...


@dataclass(frozen=True, slots=True)
class TaxonomySubject:
    """A subject under a subfield."""

    id: UUID
    name: dict[str, str]


@dataclass(frozen=True, slots=True)
class TaxonomySubfield:
    """A subfield with its subjects."""

    id: UUID
    name: dict[str, str]
    subjects: list[TaxonomySubject]


@dataclass(frozen=True, slots=True)
class TaxonomyField:
    """A field with its subfields."""

    id: UUID
    name: dict[str, str]
    subfields: list[TaxonomySubfield]


@dataclass(frozen=True, slots=True)
class CatalogFilter:
    """Browse filters; all optional."""

    field_id: UUID | None = None
    subfield_id: UUID | None = None
    subject_id: UUID | None = None
    kind: str | None = None
    grade: int | None = None
    query: str | None = None
    country: str | None = None
    online: bool | None = None
    free: bool | None = None
    max_tuition: int | None = None
    award_type: str | None = None
    scope: str | None = None
    org_id: UUID | None = None
    college_credit: str | None = None
    sort: str = "title"
    page: int = 1
    size: int = 200


@dataclass(frozen=True, slots=True)
class CatalogPage:
    """One page of the filtered catalog."""

    items: list[Opportunity]
    total: int
    page: int
    size: int


SORTS: Final = ("title", "ranking", "acceptance", "tuition")


def _sort_key(sort: str) -> Callable[[Opportunity], tuple[int, float, str]]:
    """Order by the chosen column; entries without a value go last."""

    def key(o: Opportunity) -> tuple[int, float, str]:
        d = o.draft
        value: float | None = {
            "ranking": d.ranking,
            "acceptance": d.acceptance_rate,
            "tuition": d.tuition_usd,
        }.get(sort)
        title = d.title.casefold()
        if sort == "title":
            return (0, 0.0, title)
        return (1, 0.0, title) if value is None else (0, float(value), title)

    return key


@dataclass(frozen=True, slots=True)
class OpportunityDeadline:
    """A dated event of a saved entry, for calendars and reminders."""

    opportunity_id: UUID
    title: str
    day: dt.date
    kind: str
    projected: bool


@dataclass(frozen=True, slots=True)
class PlanView:
    """A student's saved entries with the catalog rows and analytics."""

    entries: list[PlanEntry]
    catalog: dict[UUID, Opportunity]
    analytics: PlanAnalytics
    deadlines: list[OpportunityDeadline]


def tree(nodes: list[TaxonomyNode]) -> list[TaxonomyField]:
    """Nest the flat node list."""
    kids: dict[UUID | None, list[TaxonomyNode]] = {}
    for n in nodes:
        kids.setdefault(n.parent_id, []).append(n)

    def ordered(parent: UUID | None, level: str) -> list[TaxonomyNode]:
        rows = [n for n in kids.get(parent, []) if n.level == level]
        return sorted(rows, key=lambda n: (n.position, str(n.id)))

    return [
        TaxonomyField(
            f.id,
            f.names,
            [
                TaxonomySubfield(
                    s.id,
                    s.names,
                    [TaxonomySubject(j.id, j.names) for j in ordered(s.id, "subject")],
                )
                for s in ordered(f.id, "subfield")
            ],
        )
        for f in ordered(None, "field")
    ]


def _parents(nodes: list[TaxonomyNode]) -> tuple[dict[UUID, UUID], dict[UUID, UUID]]:
    """Map subject → subfield and subject → field."""
    by_id = {n.id: n for n in nodes}
    sub: dict[UUID, UUID] = {}
    fld: dict[UUID, UUID] = {}
    for n in nodes:
        if n.level == "subject" and n.parent_id in by_id:
            parent = by_id[n.parent_id]
            sub[n.id] = parent.id
            if parent.parent_id is not None:
                fld[n.id] = parent.parent_id
    return sub, fld


def submitter_role(ctx: AdmissionContext) -> SubmitterRole:
    """How the submitter is shown to moderators."""
    if Role.ADMIN in ctx.actor.roles:
        return "admin"
    if ctx.admission.is_staff:
        return "staff"
    if ctx.admission.is_applicant or Role.STUDENT in ctx.actor.roles:
        return "student"
    return "helper"


def _https(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise InvalidProofUrlError()


def _matches_program(d: OpportunityDraft, f: CatalogFilter) -> bool:
    """The country, online, free and tuition-cap filters."""
    if f.country is not None and (d.country or "").casefold() != f.country.casefold():
        return False
    if f.online is not None and d.online != f.online:
        return False
    if f.free is not None and (d.tuition_usd == 0) != f.free:
        return False
    return f.max_tuition is None or (
        d.tuition_usd is not None and d.tuition_usd <= f.max_tuition
    )


async def _any_org(org_id: UUID) -> bool:
    return True


def _matches_award(d: OpportunityDraft, f: CatalogFilter) -> bool:
    """The award type, scope, organization and college-credit filters."""
    return (
        (f.award_type is None or d.award_type == f.award_type)
        and (f.scope is None or d.scope == f.scope)
        and (f.org_id is None or d.org_id == f.org_id)
        and (f.college_credit is None or d.college_credit == f.college_credit)
    )


class OpportunityService:
    """Everyone in the app submits; administrators and grantees moderate."""

    def __init__(
        self,
        uow_factory: OppUowFactory,
        access: AccessPolicy,
        clock: Clock,
        lms: LmsCourseLookup | None = None,
        limiter: RateLimiter | None = None,
        org_exists: Callable[[UUID], Awaitable[bool]] | None = None,
    ) -> None:
        """Keep the collaborators; `lms` is None where LMS is not built."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock
        self._lms = lms
        self._limiter = limiter
        self._org_exists = org_exists or _any_org

    # - - - Roles - - -

    def can_moderate(self, ctx: AdmissionContext) -> bool:
        """Administrators, and staff holding a live `opportunities:moderate` grant."""
        if Role.ADMIN in ctx.actor.roles:
            return True
        now = self._clock.now()
        return any(
            a.active_at(now)
            and KIND_ROLE.get(a.role.kind) in ctx.actor.roles
            and Permission.OPPORTUNITIES_MODERATE in a.role.effective_permissions
            for a in ctx.assignments
        )

    def may_submit(self, ctx: AdmissionContext) -> bool:
        """Students, staff, helpers (alumni, consultants) and moderators."""
        return (
            ctx.admission.may_enter
            or Role.STUDENT in ctx.actor.roles
            or self.can_moderate(ctx)
        )

    def _require_moderator(self, ctx: AdmissionContext) -> None:
        if not self.can_moderate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": "opportunities:moderate"}
            )

    # - - - Taxonomy - - -

    async def taxonomy(self) -> list[TaxonomyField]:
        """The whole tree."""
        async with self._uow() as uow:
            return tree(await uow.opportunities.taxonomy())

    async def save_node(
        self,
        ctx: AdmissionContext,
        *,
        node_id: UUID | None,
        level: TaxonomyLevel,
        parent_id: UUID | None,
        names: dict[str, str],
        position: int,
    ) -> TaxonomyNode:
        """Create or rename a node (administrators)."""
        self._require_moderator(ctx)
        clean = {k: v.strip() for k, v in names.items() if k in LOCALES and v.strip()}
        if not clean or any(len(v) > NAME_MAX for v in clean.values()):
            raise ValidationFailedError(params={"field": "names"})
        async with self._uow() as uow:
            repo = uow.opportunities
            want = PARENT_LEVEL[level]
            if want is None and parent_id is not None:
                raise ValidationFailedError(params={"field": "parent_id"})
            if want is not None:
                parent = await repo.get_node(parent_id) if parent_id else None
                if parent is None or parent.level != want:
                    raise ValidationFailedError(params={"field": "parent_id"})
            if node_id is not None:
                current = await repo.get_node(node_id)
                if current is None:
                    raise AdmissionNotFoundError()
                if current.level != level:
                    raise ValidationFailedError(params={"field": "level"})
            node = TaxonomyNode(node_id or new_id(), level, parent_id, clean, position)
            saved = await repo.save_node(node)
            self._audit(
                uow, ctx, "opportunity.taxonomy_saved", "opportunity_taxonomy", saved.id
            )
            await uow.commit()
        return saved

    async def delete_node(self, ctx: AdmissionContext, node_id: UUID) -> None:
        """Delete a node unless a published entry uses one of its subjects."""
        self._require_moderator(ctx)
        async with self._uow() as uow:
            nodes = await uow.opportunities.taxonomy()
            if not any(n.id == node_id for n in nodes):
                raise AdmissionNotFoundError()
            ids = {node_id}
            grew = True
            while grew:
                more = {n.id for n in nodes if n.parent_id in ids} - ids
                grew = bool(more)
                ids |= more
            subjects = [n.id for n in nodes if n.id in ids and n.level == "subject"]
            if subjects and await uow.opportunities.node_in_use(subjects):
                raise InvalidTransitionError(params={"status": "in_use"})
            await uow.opportunities.delete_node(node_id)
            self._audit(
                uow,
                ctx,
                "opportunity.taxonomy_deleted",
                "opportunity_taxonomy",
                node_id,
            )
            await uow.commit()

    # - - - Submissions - - -

    async def _validate(self, draft: OpportunityDraft, subjects: set[UUID]) -> None:
        bad = draft.problems()
        if bad:
            raise ValidationFailedError(params={"field": bad[0]})
        for url in draft.urls():
            _https(url)
        if not set(draft.subject_ids) <= subjects:
            raise ValidationFailedError(params={"field": "subject_ids"})
        courses = [draft.lms_course_id] + [m.lms_course_id for m in draft.materials]
        for course_id in {c for c in courses if c is not None}:
            if self._lms is None or await self._lms.course_title(course_id) is None:
                raise ValidationFailedError(params={"field": "lms_course_id"})
        if draft.org_id is not None and not await self._org_exists(draft.org_id):
            raise ValidationFailedError(params={"field": "org_id"})

    async def submit(
        self,
        ctx: AdmissionContext,
        draft: OpportunityDraft,
        *,
        target_id: UUID | None = None,
    ) -> OpportunitySubmission:
        """Queue a new entry or an edit of `target_id` for moderation."""
        if not self.may_submit(ctx):
            raise AdmissionForbiddenError(params={"permission": "opportunities:submit"})
        async with self._uow() as uow:
            repo = uow.opportunities
            nodes = await repo.taxonomy()
            await self._validate(draft, {n.id for n in nodes if n.level == "subject"})
            if self._limiter is not None and submitter_role(ctx) == "student":
                await self._limiter.hit(
                    f"admission:opportunity_submit:{ctx.user_id}",
                    limit=STUDENT_SUBMIT_LIMIT,
                    window_seconds=_DAY,
                )
            if target_id is not None and await repo.get(target_id) is None:
                raise AdmissionNotFoundError()
            saved = await repo.add_submission(
                OpportunitySubmission(
                    id=new_id(),
                    target_id=target_id,
                    payload=draft.to_payload(),
                    note=draft.note,
                    status="pending",
                    submitted_by=ctx.user_id,
                    submitter_role=submitter_role(ctx),
                    created_at=self._clock.now(),
                )
            )
            self._audit(
                uow, ctx, "opportunity.submitted", "opportunity_submission", saved.id
            )
            await uow.commit()
        return saved

    async def submissions(
        self, ctx: AdmissionContext, *, status: str | None
    ) -> list[OpportunitySubmission]:
        """Moderators see all; everyone else their own."""
        if not self.may_submit(ctx):
            raise AdmissionForbiddenError(params={"permission": "opportunities:submit"})
        own = None if self.can_moderate(ctx) else ctx.user_id
        async with self._uow() as uow:
            return await uow.opportunities.list_submissions(
                status=status, submitted_by=own
            )

    async def review(
        self,
        ctx: AdmissionContext,
        submission_id: UUID,
        *,
        approve: bool,
        reason: str | None,
        lock_version: int,
    ) -> OpportunitySubmission:
        """Approve (publishing it) or reject with a reason."""
        self._require_moderator(ctx)
        if reason is not None and len(reason) > REASON_MAX:
            raise ValidationFailedError(params={"field": "reason"})
        async with self._uow() as uow:
            repo = uow.opportunities
            current = await repo.get_submission(submission_id)
            if current is None:
                raise AdmissionNotFoundError()
            try:
                status = review_transition(current.status, approve, reason)
            except ValueError:
                raise InvalidTransitionError(params={"status": current.status})
            except LookupError:
                raise ValidationFailedError(params={"field": "reason"})
            applied = None
            if approve:
                nodes = await repo.taxonomy()
                draft = current.draft
                await self._validate(
                    draft, {n.id for n in nodes if n.level == "subject"}
                )
                applied = await repo.apply(
                    draft, target_id=current.target_id, by=current.submitted_by
                )
            saved = await repo.save_review(
                dataclasses.replace(
                    current,
                    status=status,
                    reviewed_by=ctx.user_id,
                    reviewed_at=self._clock.now(),
                    reason=(reason or "").strip() or None,
                    applied_id=applied,
                ),
                expected_lock=lock_version,
            )
            self._audit(
                uow,
                ctx,
                f"opportunity.submission_{status}",
                "opportunity",
                applied or current.id,
                {"submission_id": str(current.id)},
            )
            await uow.commit()
        return saved

    async def set_archived(
        self, ctx: AdmissionContext, opportunity_id: UUID, archived: bool
    ) -> None:
        """Hide or restore a published entry (administrators)."""
        self._require_moderator(ctx)
        async with self._uow() as uow:
            if await uow.opportunities.get(opportunity_id) is None:
                raise AdmissionNotFoundError()
            await uow.opportunities.set_archived(opportunity_id, archived)
            self._audit(
                uow,
                ctx,
                "opportunity.archived" if archived else "opportunity.restored",
                "opportunity",
                opportunity_id,
            )
            await uow.commit()

    # - - - Browsing - - -

    async def catalog(self, f: CatalogFilter) -> CatalogPage:
        """One page of the filtered, sorted catalog."""
        rows = await self.browse(f)
        rows.sort(key=_sort_key(f.sort))
        start = (f.page - 1) * f.size
        return CatalogPage(rows[start : start + f.size], len(rows), f.page, f.size)

    async def browse(self, f: CatalogFilter) -> list[Opportunity]:
        """Live entries matching the filters, by title."""
        async with self._uow() as uow:
            nodes = await uow.opportunities.taxonomy()
            rows = await uow.opportunities.list_published()
        sub, fld = _parents(nodes)
        q = (f.query or "").strip().casefold()

        def keep(o: Opportunity) -> bool:
            d = o.draft
            subs = set(d.subject_ids)
            return (
                (f.kind is None or d.kind == f.kind)
                and (f.grade is None or not d.grades or f.grade in d.grades)
                and (f.subject_id is None or f.subject_id in subs)
                and (
                    f.subfield_id is None or f.subfield_id in {sub.get(s) for s in subs}
                )
                and (f.field_id is None or f.field_id in {fld.get(s) for s in subs})
                and _matches_program(d, f)
                and _matches_award(d, f)
                and (
                    not q
                    or q in d.title.casefold()
                    or q in (d.provider or "").casefold()
                    or q in (d.summary or "").casefold()
                    or q in (d.host_institution or "").casefold()
                    or q in (d.location or "").casefold()
                )
            )

        return sorted(filter(keep, rows), key=lambda o: o.draft.title.casefold())

    async def get(self, opportunity_id: UUID) -> Opportunity:
        """One live entry."""
        async with self._uow() as uow:
            row = await uow.opportunities.get(opportunity_id)
        if row is None or row.archived:
            raise AdmissionNotFoundError()
        return row

    def upcoming(self, o: Opportunity) -> list[DatedEvent]:
        """Next dates of an entry within the planning horizon."""
        today = self._clock.now().date()
        return upcoming_dates(o.draft, today, today + dt.timedelta(days=HORIZON_DAYS))

    # - - - Plans - - -

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner or not ctx.admission.is_applicant:
            raise AdmissionForbiddenError(params={"permission": "list:edit"})

    async def save_to_plan(
        self,
        ctx: AdmissionContext,
        opportunity_id: UUID,
        *,
        planned_grade: int | None,
        note: str | None,
    ) -> PlanEntry:
        """Save (or move) an entry in the caller's plan."""
        await self._owner(ctx)
        if planned_grade is not None and planned_grade not in GRADES:
            raise ValidationFailedError(params={"field": "planned_grade"})
        if note is not None and len(note) > REASON_MAX:
            raise ValidationFailedError(params={"field": "note"})
        async with self._uow() as uow:
            repo = uow.opportunities
            row = await repo.get(opportunity_id)
            if row is None or row.archived:
                raise AdmissionNotFoundError()
            current = await repo.plan(ctx.user_id)
            known = next(
                (e for e in current if e.opportunity_id == opportunity_id), None
            )
            if known is None and len(current) >= MAX_PLAN_ITEMS:
                raise ItemLimitError(params={"limit": MAX_PLAN_ITEMS})
            saved = await repo.save_plan_entry(
                PlanEntry(
                    id=known.id if known else new_id(),
                    student_id=ctx.user_id,
                    opportunity_id=opportunity_id,
                    planned_grade=planned_grade,
                    note=note,
                    created_at=known.created_at if known else self._clock.now(),
                )
            )
            await uow.commit()
        return saved

    async def remove_from_plan(
        self, ctx: AdmissionContext, opportunity_id: UUID
    ) -> None:
        """Drop an entry from the caller's plan."""
        await self._owner(ctx)
        async with self._uow() as uow:
            if not await uow.opportunities.delete_plan_entry(
                ctx.user_id, opportunity_id
            ):
                raise AdmissionNotFoundError()
            await uow.commit()

    async def plan_of(self, ctx: AdmissionContext, student_id: UUID) -> PlanView:
        """A plan with analytics; staff need `list:read` over the student."""
        if student_id != ctx.user_id:
            await self._access.require(
                ctx,
                student_id,
                Permission.LIST_READ,
                object_type="opportunity_plan",
            )
        else:
            await self._owner(ctx)
        return await self._plan_view(student_id)

    async def _plan_view(self, student_id: UUID) -> PlanView:
        async with self._uow() as uow:
            repo = uow.opportunities
            entries = await repo.plan(student_id)
            nodes = await repo.taxonomy()
            catalog: dict[UUID, Opportunity] = {}
            for e in entries:
                row = await repo.get(e.opportunity_id)
                if row is not None:
                    catalog[row.id] = row
        today = self._clock.now().date()
        horizon = today + dt.timedelta(days=HORIZON_DAYS)
        _, fld = _parents(nodes)
        return PlanView(
            entries=entries,
            catalog=catalog,
            analytics=analyse(entries, catalog, fld, today, horizon),
            deadlines=_deadlines(entries, catalog, today, horizon),
        )

    async def deadlines_for(
        self, student_id: UUID, start: dt.date, end: dt.date
    ) -> list[OpportunityDeadline]:
        """Dated events of a student's saved entries in [start, end].

        No access check: the calendar caller already resolved the student.
        """
        view = await self._plan_view(student_id)
        return _deadlines(view.entries, view.catalog, start, end)

    def _audit(
        self,
        uow: OpportunityUnitOfWork,
        ctx: AdmissionContext,
        action: str,
        object_type: str,
        object_id: UUID,
        meta: dict[str, str] | None = None,
    ) -> None:
        uow.access.audit(
            AuditEvent(
                action=action,
                actor_id=ctx.user_id,
                student_id=None,
                object_type=object_type,
                object_id=object_id,
                meta=meta or {},
            )
        )


def _deadlines(
    entries: list[PlanEntry],
    catalog: dict[UUID, Opportunity],
    today: dt.date,
    horizon: dt.date,
) -> list[OpportunityDeadline]:
    out = [
        OpportunityDeadline(o.id, o.draft.title, ev.day, ev.kind, ev.projected)
        for e in entries
        if (o := catalog.get(e.opportunity_id)) is not None and not o.archived
        for ev in upcoming_dates(o.draft, today, horizon)
    ]
    return sorted(out, key=lambda d: (d.day, d.title))
