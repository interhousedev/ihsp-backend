"""Schemas of the staff catalog proposals (`/v1/admission/staff/catalog/*`)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.admission.domain.catalog_proposals import CatalogProposal
from app.modules.admission.domain.supp_prompts import (
    MAX_PROMPT_LEN,
    MAX_PROPOSED_PROMPTS,
    MAX_URL_LEN,
    MAX_WORD_LIMIT,
)

from pydantic import BaseModel, Field


class CatalogFactIn(BaseModel):
    """One international fact with the page it comes from."""

    value: Any
    source_url: str = Field(max_length=2000)
    year: int = Field(ge=2000, le=2100)
    note: str | None = Field(default=None, max_length=300)


class CatalogFactOut(BaseModel):
    """A fact of a proposal."""

    value: Any
    source_url: str
    year: int
    note: str | None = None


class FactSpecOptionOut(BaseModel):
    """One allowed value of a choice fact."""

    value: str
    label: str


class FactSpecPartOut(BaseModel):
    """One part of a composite fact (range ends, factor levels)."""

    key: str
    label: str
    min: float | None
    max: float | None
    step: float | None


class FactSpecItemOut(BaseModel):
    """One fact the staff form can fill in."""

    key: str
    label: str
    kind: str
    options: list[FactSpecOptionOut]
    parts: list[FactSpecPartOut]
    min: float | None
    max: float | None
    step: float | None
    unit: str | None
    value_shape: str = Field(
        description="Shape of `value` in a proposal fact, as text."
    )
    example: Any = Field(description="A valid sample `value` of this fact.")


class FactSpecGroupOut(BaseModel):
    """A group of facts on the staff form."""

    key: str
    label: str
    facts: list[FactSpecItemOut]


class FactSpecOut(BaseModel):
    """The registry of international facts, labelled in the caller's language."""

    groups: list[FactSpecGroupOut]


class CatalogFieldsIn(BaseModel):
    """Plain fields of an institution or scholarship; unknown keys are ignored.

    Institutions: name, country (required when creating), name_local, city,
    website_domain, kind, size_band, setting, languages, aliases, logo_url,
    logo_zoom, logo_fit, logo_aspect, cover_url. Scholarships: name, provider,
    basis (required when creating), institution_id, country, coverage_pct_min,
    coverage_pct_max, covers, eligibility, url, cycle. Values are checked on save.
    """

    name: Any = Field(default=None, description="Name, at most 200 characters.")
    country: Any = Field(
        default=None, description="ISO 3166-1 alpha-2 code, e.g. `GB`; stored upper."
    )
    name_local: Any = Field(default=None, description="Name in the local language.")
    city: Any = Field(default=None, description="City, at most 120 characters.")
    website_domain: Any = Field(
        default=None, description="Site domain without scheme, e.g. `ox.ac.uk`."
    )
    kind: Any = Field(
        default=None, description="university | college | foundation_provider."
    )
    size_band: Any = Field(default=None, description="Size band label, <= 10 chars.")
    setting: Any = Field(
        default=None, description="big_city | college_town | campus | small_city."
    )
    languages: Any = Field(default=None, description="List of teaching languages.")
    aliases: Any = Field(default=None, description="List of other names, <= 50.")
    logo_url: Any = Field(default=None, description="https image address.")
    logo_zoom: Any = Field(default=None, description="Logo zoom, 0.5 to 3.0.")
    logo_fit: Any = Field(default=None, description="circle | contain.")
    logo_aspect: Any = Field(default=None, description="Logo width / height ratio.")
    cover_url: Any = Field(default=None, description="https cover image address.")
    provider: Any = Field(
        default=None, description="Scholarship: institution|government|foundation."
    )
    basis: Any = Field(
        default=None,
        description="Scholarship: merit | need | government | sports | work_study.",
    )
    institution_id: Any = Field(default=None, description="Scholarship: school id.")
    coverage_pct_min: Any = Field(default=None, description="Scholarship: 0-100.")
    coverage_pct_max: Any = Field(default=None, description="Scholarship: 0-100.")
    covers: Any = Field(default=None, description="Scholarship: what it covers.")
    eligibility: Any = Field(default=None, description="Scholarship: JSON object.")
    url: Any = Field(default=None, description="Scholarship: page address.")
    cycle: Any = Field(default=None, description="Scholarship: start year, 2000-2100.")


class SuppPromptProposalIn(BaseModel):
    """One supplement prompt of a proposal, with the page it was read on."""

    cycle: str = Field(
        pattern=r"^\d{4}-\d{2}$", description='Admission cycle, e.g. "2025-26".'
    )
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LEN)
    word_limit: int | None = Field(default=None, ge=1, le=MAX_WORD_LIMIT)
    required: bool = True
    source_url: str = Field(
        max_length=MAX_URL_LEN, pattern=r"^https://", description="https page."
    )


class SuppPromptProposalOut(BaseModel):
    """A supplement prompt carried by a proposal."""

    cycle: str
    prompt: str
    word_limit: int | None
    required: bool
    source_url: str


class CatalogProposalIn(BaseModel):
    """Propose a new institution or scholarship, or an edit of an existing one."""

    kind: Literal["institution", "scholarship"]
    target_id: UUID | None = None
    fields: CatalogFieldsIn = Field(default_factory=CatalogFieldsIn)
    supp_prompts: list[SuppPromptProposalIn] = Field(
        default_factory=list,
        max_length=MAX_PROPOSED_PROMPTS,
        description="Institutions only. Applied like the staff supplement PUT.",
    )
    facts: dict[str, CatalogFactIn] = Field(default_factory=dict)
    source_url: str = Field(max_length=2000)
    note: str | None = Field(default=None, max_length=1000)


class CatalogReviewIn(BaseModel):
    """Approve or reject a pending proposal."""

    approve: bool
    note: str | None = Field(default=None, max_length=500)
    lock_version: int


class CatalogProposalOut(BaseModel):
    """A stored proposal."""

    id: UUID
    kind: Literal["institution", "scholarship"]
    target_id: UUID | None
    fields: dict[str, Any]
    facts: dict[str, CatalogFactOut] = Field(default_factory=dict)
    supp_prompts: list[SuppPromptProposalOut] = Field(default_factory=list)
    source_url: str
    note: str | None
    status: Literal["pending", "approved", "rejected"]
    proposed_by: UUID
    created_at: datetime
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    applied_id: UUID | None
    lock_version: int

    @classmethod
    def of(cls, p: CatalogProposal) -> "CatalogProposalOut":
        """Map a proposal."""
        return cls(
            id=p.id,
            kind=p.kind,
            target_id=p.target_id,
            fields=p.payload,
            facts={k: CatalogFactOut(**v) for k, v in p.facts.items()},
            supp_prompts=[SuppPromptProposalOut(**x) for x in p.supp_prompts],
            source_url=p.source_url,
            note=p.note,
            status=p.status,
            proposed_by=p.proposed_by,
            created_at=p.created_at,
            reviewed_by=p.reviewed_by,
            reviewed_at=p.reviewed_at,
            review_note=p.review_note,
            applied_id=p.applied_id,
            lock_version=p.lock_version,
        )


class CatalogProposalListOut(BaseModel):
    """Proposals the caller may see, and whether the caller may review them."""

    items: list[CatalogProposalOut]
    can_review: bool
