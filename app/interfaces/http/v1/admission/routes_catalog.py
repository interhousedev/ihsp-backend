"""Catalog facets, study-field taxonomy and the staff institution view."""

from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, AnyContext, ContainerDep
from app.interfaces.http.v1.admission.routes_chooser import (
    DeadlineOut,
    Lang,
    dated_deadlines,
)
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.domain.catalog_display import resolve_logo_fit
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.domain.supp_prompts import (
    MAX_CHAR_LIMIT,
    MAX_PROMPT_LEN,
    MAX_PROMPTS,
    MAX_URL_LEN,
    CyclePrompts,
    PromptStatus,
    SuppPrompt,
)

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class FacetOptionOut(BaseModel):
    """One selectable value of a filter."""

    value: str
    label: str


class FacetOut(BaseModel):
    """A filter of the catalog: the query parameter, its label and values."""

    param: str
    label: str
    kind: str
    options: list[FacetOptionOut]
    max: int | None = None


class StudyItemOut(BaseModel):
    """A canonical field of study; `id` is accepted by the `field` filter."""

    id: str
    label: str


class StudyGroupOut(BaseModel):
    """A group of fields of study."""

    id: str
    label: str
    items: list[StudyItemOut]


class StaffFactOut(BaseModel):
    """A fact with its source and the raw note, for staff only."""

    key: str
    value: Any
    source_url: str | None
    year: int | None
    note: str | None
    verified: bool


class StaffInstitutionOut(BaseModel):
    """Raw catalog view with notes; the student payload never carries them."""

    id: UUID
    name: str
    facts: list[StaffFactOut]
    deadlines: list[DeadlineOut]
    logo_zoom: float
    logo_fit: str


class LogoPatchIn(BaseModel):
    """Logo display fields to change."""

    logo_zoom: float | None = Field(default=None, ge=0.5, le=3.0)
    logo_fit: Literal["circle", "contain"] | None = None


class SuppPromptOut(BaseModel):
    """A prompt of a cycle; `status` compares it with the cycle before.

    `previous_text` is the old wording of a `changed` prompt.
    """

    position: int
    prompt: str
    word_limit: int | None
    limit_unit: Literal["words", "characters"]
    limit_min: int | None
    choice_group: str | None
    required: bool
    source_url: str | None
    status: PromptStatus
    previous_text: str | None


class SuppCycleOut(BaseModel):
    """The prompts of one admission cycle, e.g. `2025-26`."""

    cycle: str
    prompts: list[SuppPromptOut]


class SuppPromptIn(BaseModel):
    """One prompt to store; the list order gives the position."""

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LEN)
    word_limit: int | None = Field(default=None, ge=1, le=MAX_CHAR_LIMIT)
    limit_unit: Literal["words", "characters"] = "words"
    limit_min: int | None = Field(default=None, ge=1)
    choice_group: str | None = Field(default=None, max_length=40)
    required: bool = True
    source_url: str | None = Field(default=None, max_length=MAX_URL_LEN)


class SuppPromptsPutIn(BaseModel):
    """The full prompt list of a cycle."""

    prompts: list[SuppPromptIn] = Field(max_length=MAX_PROMPTS)


def _cycles_out(cycles: list[CyclePrompts]) -> list[SuppCycleOut]:
    return [
        SuppCycleOut(
            cycle=c.cycle,
            prompts=[
                SuppPromptOut(
                    position=p.prompt.position,
                    prompt=p.prompt.prompt,
                    word_limit=p.prompt.word_limit,
                    required=p.prompt.required,
                    source_url=p.prompt.source_url,
                    limit_unit=p.prompt.limit_unit,
                    limit_min=p.prompt.limit_min,
                    choice_group=p.prompt.choice_group,
                    status=p.status,
                    previous_text=p.previous_text,
                )
                for p in c.prompts
            ],
        )
        for c in cycles
    ]


async def get_supp_prompts(
    institution_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> list[SuppCycleOut]:
    """Supplemental prompts per cycle, newest first, with changes since last year."""
    return _cycles_out(await container.admission.supp_prompts.cycles(institution_id))


async def put_staff_supp_prompts(
    institution_id: UUID,
    cycle: str,
    body: SuppPromptsPutIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> list[SuppCycleOut]:
    """Replace the prompts of one cycle (curator roles); returns every cycle."""
    prompts = [
        SuppPrompt(
            i,
            p.prompt,
            p.word_limit,
            p.required,
            p.source_url,
            p.limit_unit,
            p.limit_min,
            p.choice_group,
        )
        for i, p in enumerate(body.prompts)
    ]
    cycles = await container.admission.supp_prompts.replace(
        ctx, institution_id, cycle, prompts
    )
    return _cycles_out(cycles)


async def get_facets(
    container: ContainerDep, ctx: AdmissionCtx, accept_language: Lang = None
) -> list[FacetOut]:
    """Describe every catalog filter with localized labels and options."""
    rows = await container.admission.catalog.facets(_locale(accept_language))
    return [FacetOut(**r) for r in rows]


async def get_study_fields(
    container: ContainerDep, ctx: AdmissionCtx, accept_language: Lang = None
) -> list[StudyGroupOut]:
    """Fields of study grouped and deduplicated, with stable ids."""
    rows = await container.admission.catalog.study_fields(_locale(accept_language))
    return [StudyGroupOut(**r) for r in rows]


async def get_staff_institution(
    institution_id: UUID, container: ContainerDep, ctx: AnyContext
) -> StaffInstitutionOut:
    """Raw facts with their notes (staff and catalog curators only)."""
    if not (
        ctx.admission.is_staff or container.admission.catalog_proposals.can_review(ctx)
    ):
        raise AdmissionForbiddenError(params={"permission": "catalog:read"})
    return await _staff_view(container, institution_id)


async def _staff_view(
    container: ContainerDep, institution_id: UUID
) -> StaffInstitutionOut:
    inst = await container.admission.catalog.institution(institution_id)
    raw = inst.facts.get("deadlines")

    return StaffInstitutionOut(
        id=inst.id,
        name=inst.name,
        facts=[
            StaffFactOut(
                key=k,
                value=f.value,
                source_url=f.source_url,
                year=f.year,
                note=f.note,
                verified=f.verified,
            )
            for k, f in inst.facts.items()
        ],
        deadlines=dated_deadlines(raw.value if raw else None),
        logo_zoom=inst.logo_zoom,
        logo_fit=resolve_logo_fit(inst.logo_fit, inst.logo_aspect),
    )


async def patch_staff_institution(
    institution_id: UUID, body: LogoPatchIn, container: ContainerDep, ctx: AnyContext
) -> StaffInstitutionOut:
    """Change the logo zoom or fit of an institution (curator roles)."""
    await container.admission.catalog_proposals.edit_logo(
        ctx, institution_id, zoom=body.logo_zoom, fit=body.logo_fit
    )
    return await _staff_view(container, institution_id)


_R = router.add_api_route
_R(
    "/catalog/facets",
    get_facets,
    methods=["GET"],
    response_model=list[FacetOut],
    operation_id="admission_catalog_facets",
)
_R(
    "/catalog/study-fields",
    get_study_fields,
    methods=["GET"],
    response_model=list[StudyGroupOut],
    operation_id="admission_catalog_study_fields",
)
_R(
    "/staff/catalog/institutions/{institution_id}",
    get_staff_institution,
    methods=["GET"],
    response_model=StaffInstitutionOut,
    operation_id="admission_staff_catalog_institution",
)
_R(
    "/staff/catalog/institutions/{institution_id}",
    patch_staff_institution,
    methods=["PATCH"],
    response_model=StaffInstitutionOut,
    operation_id="admission_staff_catalog_institution_patch",
)
_R(
    "/catalog/institutions/{institution_id}/supp-prompts",
    get_supp_prompts,
    methods=["GET"],
    response_model=list[SuppCycleOut],
    operation_id="admission_catalog_supp_prompts",
)
_R(
    "/staff/catalog/institutions/{institution_id}/supp-prompts/{cycle}",
    put_staff_supp_prompts,
    methods=["PUT"],
    response_model=list[SuppCycleOut],
    operation_id="admission_staff_catalog_supp_prompts_put",
)
