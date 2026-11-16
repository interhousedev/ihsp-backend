"""University chooser routes: catalog, my list, estimates, affordability."""

import datetime as dt
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.modules.admission.application.chooser import ListItem
from app.modules.admission.application.estimates import EstimateView
from app.modules.admission.domain.chooser import (
    AffordabilityCheck,
    CatalogFilters,
    CatalogInstitution,
    CatalogScholarship,
)
from app.modules.admission.domain.errors import AdmissionNotFoundError

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Round = Literal["ED", "ED2", "EA", "REA", "RD", "ROLLING"]
Bucket = Literal["reach", "target", "safety"]
Status = Literal["considering", "applying", "applied", "dropped"]


class FactOut(BaseModel):
    """One cited catalog fact."""

    value: Any
    source_url: str | None
    year: int | None
    note: str | None
    verified: bool


class InstitutionOut(BaseModel):
    """A catalog institution with its cited facts."""

    id: UUID
    slug: str | None
    name: str
    country: str
    city: str | None
    verified: bool
    facts: dict[str, FactOut]
    coa_total: Decimal | None
    coa_currency: str | None
    aid_basis: str | None
    merit_available: bool | None
    scholarship_count: int

    @classmethod
    def of(cls, i: CatalogInstitution) -> "InstitutionOut":
        """Map the domain institution."""
        return cls(
            id=i.id,
            slug=i.slug,
            name=i.name,
            country=i.country,
            city=i.city,
            verified=i.verified,
            facts={
                k: FactOut(
                    value=f.value,
                    source_url=f.source_url,
                    year=f.year,
                    note=f.note,
                    verified=f.verified,
                )
                for k, f in i.facts.items()
            },
            coa_total=i.coa_total,
            coa_currency=i.coa_currency,
            aid_basis=i.aid_basis,
            merit_available=i.merit_available,
            scholarship_count=i.scholarship_count,
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
    affordability: AffordabilityOut | None
    estimate: EstimateOut
    lock_version: int

    @classmethod
    def of(cls, i: ListItem) -> "ListEntryOut":
        """Map the list item."""
        e = i.entry
        return cls(
            id=e.id,
            student_id=e.student_id,
            institution=InstitutionOut.of(i.institution),
            round=e.round,
            status=e.status,
            bucket=e.bucket,
            notes=e.notes,
            label_override=e.label_override,
            override_note=e.override_note,
            affordability_status=e.affordability_status,
            affordability=(
                AffordabilityOut.of(i.affordability)
                if i.affordability is not None and i.amounts_visible
                else None
            ),
            estimate=EstimateOut.of(i.estimate),
            lock_version=e.lock_version,
        )


class ListAddIn(BaseModel):
    """Add an institution to my list."""

    model_config = ConfigDict(extra="forbid")

    institution_id: UUID
    round: Round = "RD"
    bucket: Bucket | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ListPatchIn(BaseModel):
    """Change an entry; send `bucket: null` explicitly to clear it."""

    model_config = ConfigDict(extra="forbid")

    lock_version: int
    round: Round | None = None
    status: Status | None = None
    bucket: Bucket | None = None
    notes: str | None = Field(default=None, max_length=2000)


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
    study_type: str | None = None,
    max_crime_index: float | None = None,
    aid: str | None = None,
    scholarships: bool | None = None,
    max_cost: Decimal | None = None,
    cursor: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
) -> InstitutionPageOut:
    """Filter the catalog by field, city, study type, safety, aid and cost."""
    page = await container.admission.catalog.search(
        CatalogFilters(
            q=q,
            country=country,
            field=field,
            city_type=city_type,
            study_type=study_type,
            max_crime_index=max_crime_index,
            aid=aid,
            scholarships=scholarships,
            max_cost=max_cost,
        ),
        cursor=cursor,
        limit=limit,
    )
    return InstitutionPageOut(
        items=[InstitutionOut.of(i) for i in page.items],
        next_cursor=page.next_cursor,
    )


async def get_institution(
    institution_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> InstitutionOut:
    """Return one institution with cited facts."""
    return InstitutionOut.of(
        await container.admission.catalog.institution(institution_id)
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


async def get_my_list(container: ContainerDep, ctx: AdmissionCtx) -> list[ListEntryOut]:
    """Return my university list."""
    items = await container.admission.chooser.view(ctx, ctx.user_id)
    return [ListEntryOut.of(i) for i in items]


async def get_student_list(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> list[ListEntryOut]:
    """Return a student's list as the caller may see it."""
    items = await container.admission.chooser.view(ctx, student_id)
    return [ListEntryOut.of(i) for i in items]


async def add_to_list(
    body: ListAddIn, container: ContainerDep, ctx: AdmissionCtx
) -> ListEntryOut:
    """Add an institution to my list."""
    item = await container.admission.chooser.add(
        ctx,
        body.institution_id,
        round_=body.round,
        bucket=body.bucket,
        notes=body.notes,
    )
    return ListEntryOut.of(item)


async def patch_list_entry(
    entry_id: UUID, body: ListPatchIn, container: ContainerDep, ctx: AdmissionCtx
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
        clear_bucket="bucket" in body.model_fields_set and body.bucket is None,
    )
    return ListEntryOut.of(item)


async def delete_list_entry(
    entry_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> None:
    """Remove an institution from my list."""
    await container.admission.chooser.remove(ctx, entry_id)


async def get_entry_estimate(
    entry_id: UUID, container: ContainerDep, ctx: AdmissionCtx
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
    return ListEntryOut.of(next(i for i in items if i.entry.id == entry.id))


async def check_affordability(
    entry_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> AffordabilityOut:
    """Recompute the cost check against my budget band."""
    check, _ = await container.admission.chooser.affordability(ctx, entry_id)
    return AffordabilityOut.of(check)


async def request_sign_off(
    entry_id: UUID, container: ContainerDep, ctx: AdmissionCtx
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
