"""University chooser routes: catalog, my list, estimates, affordability."""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.chooser import ListItem
from app.modules.admission.application.estimates import EstimateView
from app.modules.admission.domain.budget import cost_after_aid
from app.modules.admission.domain.catalog_display import (
    clean_deadlines,
    highlights,
    resolve_logo_fit,
)
from app.modules.admission.domain.chooser import (
    AffordabilityCheck,
    CatalogFilters,
    CatalogInstitution,
    CatalogScholarship,
    next_deadline,
)
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.intl_fact_display import (
    detail_groups,
    importance_factors,
)
from app.shared.clock import SystemClock, local_today

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Round = Literal["ED", "ED2", "EA", "REA", "SCEA", "RD", "ROLLING"]
CatalogSort = Literal["deadline"]
Bucket = Literal["reach", "target", "safety"]
FeeStatus = Literal["unpaid", "paid", "waiver_requested", "waiver_approved"]
Status = Literal["considering", "applying", "applied", "dropped"]
CYCLE_RE = r"^[0-9]{4}-[0-9]{2}$"
Lang = Annotated[str | None, Header(alias="Accept-Language")]


class FactOut(BaseModel):
    """One cited catalog fact."""

    value: Any
    verified: bool


class SourceOut(BaseModel):
    """Where a fact came from; kept apart from the facts themselves."""

    key: str
    url: str | None
    year: int | None


class HighlightOut(BaseModel):
    """One ready-to-show line of the institution card."""

    key: str
    label: str
    value_text: str


class DeadlineOut(BaseModel):
    """One application deadline with plain text only."""

    plan: str
    date: dt.date
    notify_by: dt.date | None
    cycle: str | None
    binding: bool | None = None
    time_zone: str | None = None
    label_short: str


def dated_deadlines(raw: Any, locale: str = "en") -> list[DeadlineOut]:
    """Deadlines that have a date; a stored one without a date is not listed."""
    return [DeadlineOut(**d) for d in clean_deadlines(raw, locale) if d["date"]]


class DetailRowOut(BaseModel):
    """One fact of a school in the detail view, with display text."""

    key: str
    label: str
    kind: str
    value: Any
    value_text: str
    source_url: str | None
    year: int | None


class DetailGroupOut(BaseModel):
    """Facts of one registry group."""

    key: str
    label: str
    rows: list[DetailRowOut]


class ImportanceFactorOut(BaseModel):
    """How much one factor weighs in the school's admission decision."""

    key: str
    label: str
    importance: str


class InstitutionOut(BaseModel):
    """A catalog institution with its cited facts."""

    id: UUID
    slug: str | None
    name: str
    country: str
    city: str | None
    verified: bool
    facts: dict[str, FactOut]
    sources: list[SourceOut]
    highlights: list[HighlightOut]
    deadlines: list[DeadlineOut]
    next_deadline: dt.date | None
    aliases: list[str]
    name_local: str | None
    logo_zoom: float
    logo_fit: Literal["circle", "contain"]
    coa_total: Decimal | None
    coa_currency: str | None
    cost_after_aid: Decimal | None
    aid_basis: str | None
    merit_available: bool | None
    scholarship_count: int
    logo_url: str | None
    cover_url: str | None
    website_url: str | None
    details: list[DetailGroupOut] = []
    factors: list[ImportanceFactorOut] = []

    @classmethod
    def of(
        cls,
        i: CatalogInstitution,
        locale: str = "en",
        *,
        today: dt.date | None = None,
        detail: bool = False,
    ) -> "InstitutionOut":
        """Map the domain institution; text is localized, notes are left out.

        `next_deadline` is the earliest deadline on or after `today` (default:
        today in Tashkent).
        `details` and `factors` are filled only when `detail` is set.
        """
        deadlines = i.facts.get("deadlines")
        return cls(
            id=i.id,
            slug=i.slug,
            name=i.name,
            country=i.country,
            city=i.city,
            verified=i.verified,
            facts={
                k: FactOut(value=f.value, verified=f.verified)
                for k, f in i.facts.items()
                if k != "deadlines"
            },
            sources=[
                SourceOut(key=k, url=f.source_url, year=f.year)
                for k, f in i.facts.items()
                if k != "deadlines" and (f.source_url or f.year)
            ],
            highlights=[HighlightOut(**h) for h in highlights(i, locale)],
            deadlines=dated_deadlines(deadlines.value if deadlines else None, locale),
            next_deadline=next_deadline(i, today or local_today(SystemClock())),
            aliases=list(i.aliases),
            name_local=i.name_local,
            logo_zoom=i.logo_zoom,
            logo_fit=resolve_logo_fit(i.logo_fit, i.logo_aspect),
            coa_total=i.coa_total,
            coa_currency=i.coa_currency,
            cost_after_aid=cost_after_aid(i.coa_total, i.coa_currency, i.aid_profile),
            aid_basis=i.aid_basis,
            merit_available=i.merit_available,
            scholarship_count=i.scholarship_count,
            logo_url=i.logo_url,
            cover_url=i.cover_url,
            website_url=(f"https://{i.website_domain}" if i.website_domain else None),
            details=(
                [DetailGroupOut(**g) for g in detail_groups(i, locale)]
                if detail
                else []
            ),
            factors=(
                [ImportanceFactorOut(**f) for f in importance_factors(i, locale)]
                if detail
                else []
            ),
        )


class InstitutionPageOut(BaseModel):
    """A page of institutions; `next_cursor` is null on the last page."""

    items: list[InstitutionOut]
    next_cursor: int | None


class ScholarshipOut(BaseModel):
    """A scholarship of the catalog."""

    id: UUID
    name: str
    provider: str
    institution_id: UUID | None
    country: str | None
    basis: str
    coverage_min: int | None
    coverage_max: int | None
    covers: list[str]
    url: str | None
    status: str
    cycle: int | None

    @classmethod
    def of(cls, s: CatalogScholarship) -> "ScholarshipOut":
        """Map the domain scholarship."""
        return cls(
            id=s.id,
            name=s.name,
            provider=s.provider,
            institution_id=s.institution_id,
            country=s.country,
            basis=s.basis,
            coverage_min=s.coverage_min,
            coverage_max=s.coverage_max,
            covers=list(s.covers),
            url=s.url,
            status=s.status,
            cycle=s.cycle,
        )


class EstimateOut(BaseModel):
    """A chance range or, for students, the bucket only."""

    label: str
    low: int | None
    high: int | None
    range_visible: bool
    calibrated: bool
    label_overridden: bool
    verified: bool
    caveats: list[str]
    missing: list[str]
    method_version: str
    sources: list[str]
    basis: dict[str, Any]

    @classmethod
    def of(cls, e: EstimateView) -> "EstimateOut":
        """Map the application view."""
        return cls(
            label=e.label,
            low=e.low,
            high=e.high,
            range_visible=e.range_visible,
            calibrated=e.calibrated,
            label_overridden=e.label_overridden,
            verified=e.verified,
            caveats=list(e.caveats),
            missing=list(e.missing),
            method_version=e.method_version,
            sources=list(e.sources),
            basis=e.basis,
        )


class AffordabilityOut(BaseModel):
    """The cost check against the budget band."""

    list_entry_id: UUID
    status: str
    coa_total: Decimal | None
    confirmed_aid: Decimal | None
    estimated_aid: Decimal | None
    gap: Decimal | None
    requested_sign_off_at: dt.datetime | None
    signed_off_at: dt.datetime | None
    sign_off_note: str | None

    @classmethod
    def of(cls, c: AffordabilityCheck) -> "AffordabilityOut":
        """Map the domain check."""
        return cls(
            list_entry_id=c.list_entry_id,
            status=c.status,
            coa_total=c.coa_total,
            confirmed_aid=c.confirmed_aid,
            estimated_aid=c.estimated_aid,
            gap=c.gap,
            requested_sign_off_at=c.requested_sign_off_at,
            signed_off_at=c.signed_off_at,
            sign_off_note=c.sign_off_note,
        )


class PlanConflictOut(BaseModel):
    """A warning about conflicting early-application plans; never blocks."""

    code: str
    severity: Literal["conflict", "check"]
    entry_ids: list[UUID]


class ListEntryOut(BaseModel):
    """A list entry with institution, estimate and affordability."""

    id: UUID
    student_id: UUID
    institution: InstitutionOut
    round: str
    status: str
    bucket: str | None
    notes: str | None
    label_override: str | None
    override_note: str | None
    affordability_status: str
    fee_status: FeeStatus
    affordability: AffordabilityOut | None
    estimate: EstimateOut
    cycle: str | None
    lock_version: int
    conflicts: list[PlanConflictOut]

    @classmethod
    def of(cls, i: ListItem, locale: str = "en", *, today: dt.date) -> "ListEntryOut":
        """Map the list item."""
        e = i.entry
        return cls(
            id=e.id,
            student_id=e.student_id,
            institution=InstitutionOut.of(i.institution, locale, today=today),
            round=e.round,
            status=e.status,
            bucket=e.bucket,
            notes=e.notes,
            label_override=e.label_override,
            override_note=e.override_note,
            affordability_status=e.affordability_status,
            fee_status=e.fee_status,
            affordability=(
                AffordabilityOut.of(i.affordability)
                if i.affordability is not None and i.amounts_visible
                else None
            ),
            estimate=EstimateOut.of(i.estimate),
            cycle=e.cycle,
            lock_version=e.lock_version,
            conflicts=[
                PlanConflictOut(
                    code=c.code, severity=c.severity, entry_ids=list(c.entry_ids)
                )
                for c in i.conflicts
            ],
        )


class ListAddIn(BaseModel):
    """Add an institution to my list."""

    model_config = ConfigDict(extra="forbid")

    institution_id: UUID
    round: Round = "RD"
    bucket: Bucket | None = None
    notes: str | None = Field(default=None, max_length=2000)
    cycle: str | None = Field(default=None, pattern=CYCLE_RE)


class ListPatchIn(BaseModel):
    """Change an entry; send `bucket: null` explicitly to clear it."""

    model_config = ConfigDict(extra="forbid")

    lock_version: int
    round: Round | None = None
    status: Status | None = None
    bucket: Bucket | None = None
    notes: str | None = Field(default=None, max_length=2000)
    cycle: str | None = Field(default=None, pattern=CYCLE_RE)
    fee_status: FeeStatus | None = None


class LabelOverrideIn(BaseModel):
    """Counselor label override; `label: null` clears it."""

    model_config = ConfigDict(extra="forbid")

    label: Bucket | None = None
    note: str | None = Field(default=None, max_length=1000)
    lock_version: int


class SignOffIn(BaseModel):
    """Counselor sign-off note."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=1000)


class SummaryOut(BaseModel):
    """AI research summary, private to the caller."""

    summary: str
    points: list[dict[str, Any]]
    missing: list[str]


async def search_institutions(
    container: ContainerDep,
    ctx: AdmissionCtx,
    q: str | None = None,
    country: str | None = None,
    field: str | None = None,
    city_type: str | None = None,
    institution_type: str | None = None,
    setting: str | None = None,
    test_policy: str | None = None,
    merit_intl: bool | None = None,
    plan: str | None = None,
    cycle: str | None = Query(None, pattern=CYCLE_RE),
    max_crime_index: float | None = None,
    aid: str | None = None,
    scholarships: bool | None = None,
    max_cost: Decimal | None = None,
    sort: CatalogSort | None = None,
    cursor: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    accept_language: Lang = None,
) -> InstitutionPageOut:
    """Search and filter the catalog; name and alias matches come first.

    `setting` is the campus setting (`city_type` is the same filter). `sort=deadline`
    lists the soonest next deadline first, institutions without one last.
    """
    today = local_today(container.clock)
    page = await container.admission.catalog.search(
        CatalogFilters(
            q=q,
            country=country,
            field=field,
            city_type=setting or city_type,
            institution_type=institution_type,
            test_policy=test_policy,
            merit_intl=merit_intl,
            plan=plan,
            cycle=cycle,
            max_crime_index=max_crime_index,
            aid=aid,
            scholarships=scholarships,
            max_cost=max_cost,
        ),
        sort=sort,
        today=today,
        cursor=cursor,
        limit=limit,
    )
    return InstitutionPageOut(
        items=[
            InstitutionOut.of(i, _locale(accept_language), today=today)
            for i in page.items
        ],
        next_cursor=page.next_cursor,
    )


async def get_institution(
    institution_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Lang = None,
) -> InstitutionOut:
    """Return one institution with localized highlights and deadlines."""
    return InstitutionOut.of(
        await container.admission.catalog.institution(institution_id),
        _locale(accept_language),
        today=local_today(container.clock),
        detail=True,
    )


async def list_scholarships(
    container: ContainerDep,
    ctx: AdmissionCtx,
    institution_id: UUID | None = None,
    country: str | None = None,
    basis: str | None = None,
    coverage_min: int | None = Query(None, ge=0, le=100),
) -> list[ScholarshipOut]:
    """List scholarships, optionally by institution, country or basis."""
    rows = await container.admission.catalog.scholarships(
        institution_id=institution_id,
        country=country,
        basis=basis,
        coverage_min=coverage_min,
    )
    return [ScholarshipOut.of(s) for s in rows]


async def summarise_institution(
    institution_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    language: Literal["uz", "ru", "en"] = "en",
) -> SummaryOut:
    """AI summary of the cited facts (private; unavailable without a model)."""
    research = container.admission.catalog_research
    if research is None:
        raise AdmissionNotFoundError()
    return SummaryOut(**await research.summarise(institution_id, language))


async def get_my_list(
    container: ContainerDep,
    ctx: StudentCtx,
    cycle: str | None = Query(None, pattern=CYCLE_RE),
    accept_language: Lang = None,
) -> list[ListEntryOut]:
    """Return my university list, optionally one cycle (`2026-27`)."""
    items = await container.admission.chooser.view(ctx, ctx.user_id, cycle)
    today = local_today(container.clock)
    return [ListEntryOut.of(i, _locale(accept_language), today=today) for i in items]


async def get_student_list(
    student_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    cycle: str | None = Query(None, pattern=CYCLE_RE),
    accept_language: Lang = None,
) -> list[ListEntryOut]:
    """Return a student's list as the caller may see it, optionally one cycle."""
    items = await container.admission.chooser.view(ctx, student_id, cycle)
    today = local_today(container.clock)
    return [ListEntryOut.of(i, _locale(accept_language), today=today) for i in items]


async def add_to_list(
    body: ListAddIn, container: ContainerDep, ctx: StudentCtx
) -> ListEntryOut:
    """Add an institution to my list."""
    item = await container.admission.chooser.add(
        ctx,
        body.institution_id,
        round_=body.round,
        bucket=body.bucket,
        notes=body.notes,
        cycle=body.cycle,
    )
    return ListEntryOut.of(item, today=local_today(container.clock))


async def patch_list_entry(
    entry_id: UUID, body: ListPatchIn, container: ContainerDep, ctx: StudentCtx
) -> ListEntryOut:
    """Change round, status, bucket or notes of my entry."""
    item = await container.admission.chooser.update(
        ctx,
        entry_id,
        lock_version=body.lock_version,
        round_=body.round,
        status=body.status,
        bucket=body.bucket,
        notes=body.notes,
        cycle=body.cycle,
        fee_status=body.fee_status,
        clear_bucket="bucket" in body.model_fields_set and body.bucket is None,
    )
    return ListEntryOut.of(item, today=local_today(container.clock))


async def delete_list_entry(
    entry_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> None:
    """Remove an institution from my list."""
    await container.admission.chooser.remove(ctx, entry_id)


async def get_entry_estimate(
    entry_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> EstimateOut:
    """Return the estimate as the caller may see it."""
    return EstimateOut.of(await container.admission.chooser.estimate(ctx, entry_id))


async def put_label_override(
    entry_id: UUID, body: LabelOverrideIn, container: ContainerDep, ctx: AdmissionCtx
) -> ListEntryOut:
    """Counselor sets or clears the reach/target/safety label."""
    svc = container.admission.chooser
    entry = await svc.override_label(
        ctx,
        entry_id,
        label=body.label,
        note=body.note,
        lock_version=body.lock_version,
    )
    items = await svc.view(ctx, entry.student_id)
    return ListEntryOut.of(
        next(i for i in items if i.entry.id == entry.id),
        today=local_today(container.clock),
    )


async def check_affordability(
    entry_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> AffordabilityOut:
    """Recompute the cost check against my budget band."""
    check, _ = await container.admission.chooser.affordability(ctx, entry_id)
    return AffordabilityOut.of(check)


async def request_sign_off(
    entry_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> AffordabilityOut:
    """Ask a counselor to sign off a gap or unknown cost."""
    check = await container.admission.chooser.request_sign_off(ctx, entry_id)
    return AffordabilityOut.of(check)


async def sign_off_affordability(
    entry_id: UUID, body: SignOffIn, container: ContainerDep, ctx: AdmissionCtx
) -> AffordabilityOut:
    """Counselor signs off an unresolved cost."""
    check = await container.admission.chooser.sign_off(ctx, entry_id, note=body.note)
    return AffordabilityOut.of(check)


for _path, _fn, _method, _model, _op, _status in (
    (
        "/catalog/institutions",
        search_institutions,
        "GET",
        InstitutionPageOut,
        "admission_search_institutions",
        200,
    ),
    (
        "/catalog/institutions/{institution_id}",
        get_institution,
        "GET",
        InstitutionOut,
        "admission_get_institution",
        200,
    ),
    (
        "/catalog/scholarships",
        list_scholarships,
        "GET",
        list[ScholarshipOut],
        "admission_list_scholarships",
        200,
    ),
    (
        "/catalog/institutions/{institution_id}/summary",
        summarise_institution,
        "POST",
        SummaryOut,
        "admission_summarise_institution",
        200,
    ),
    ("/list", get_my_list, "GET", list[ListEntryOut], "admission_get_my_list", 200),
    ("/list", add_to_list, "POST", ListEntryOut, "admission_add_to_list", 201),
    (
        "/list/{entry_id}",
        patch_list_entry,
        "PATCH",
        ListEntryOut,
        "admission_patch_list_entry",
        200,
    ),
    (
        "/list/{entry_id}",
        delete_list_entry,
        "DELETE",
        None,
        "admission_delete_list_entry",
        204,
    ),
    (
        "/list/{entry_id}/estimate",
        get_entry_estimate,
        "GET",
        EstimateOut,
        "admission_get_entry_estimate",
        200,
    ),
    (
        "/list/{entry_id}/label-override",
        put_label_override,
        "PUT",
        ListEntryOut,
        "admission_put_label_override",
        200,
    ),
    (
        "/list/{entry_id}/affordability",
        check_affordability,
        "POST",
        AffordabilityOut,
        "admission_check_affordability",
        200,
    ),
    (
        "/list/{entry_id}/affordability/request-sign-off",
        request_sign_off,
        "POST",
        AffordabilityOut,
        "admission_request_sign_off",
        200,
    ),
    (
        "/list/{entry_id}/affordability/sign-off",
        sign_off_affordability,
        "POST",
        AffordabilityOut,
        "admission_sign_off_affordability",
        200,
    ),
    (
        "/students/{student_id}/list",
        get_student_list,
        "GET",
        list[ListEntryOut],
        "admission_get_student_list",
        200,
    ),
):
    router.add_api_route(
        _path,
        _fn,
        methods=[_method],
        response_model=_model,
        status_code=_status,
        operation_id=_op,
    )
