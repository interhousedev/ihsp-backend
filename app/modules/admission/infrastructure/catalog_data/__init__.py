"""Seed catalog of universities popular with Uzbek applicants.

Every fact carries ``source_url`` and ``year``; anything not verified is ``None``
(never guessed). ``load_seed()`` validates the JSON files against the pydantic
schema below and returns plain dicts of the same shape the importers produce.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Literal

from app.modules.admission.domain.study_fields import canonical_names
from app.modules.admission.infrastructure.catalog_data.profiles import PROFILES

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

_DIR = Path(__file__).parent

CityType = Literal["urban", "suburban", "rural"]
TestPolicy = Literal["required", "optional", "blind", "flexible", "not_applicable"]
AidBasis = Literal["need_blind_full", "need_aware", "merit_only", "none"]
DeadlinePlan = Literal["ED", "ED2", "EA", "REA", "SCEA", "RD", "ROLLING", "OTHER"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(_Model):
    """A sourced value."""

    value: Any | None = None
    source_url: HttpUrl | None = None
    year: int | None = Field(default=None, ge=2000, le=2100)
    note: str | None = None


class Money(Fact):
    """Amount per year in ``currency`` (ISO 4217); fields keep the ``_usd`` legacy."""

    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class RangeFact(_Model):
    """A sourced min/max range."""

    min: float | None = None
    max: float | None = None
    source_url: HttpUrl | None = None
    year: int | None = Field(default=None, ge=2000, le=2100)
    note: str | None = None


class AvgAid(_Model):
    """The average aid package in USD and how it splits (each share 0-100).

    ``scope`` is ``intl`` for international students, ``overall`` when the
    institution publishes no international figure.
    """

    value: float | None = Field(default=None, ge=0)
    scope: Literal["intl", "overall"]
    grant_pct: int | None = Field(default=None, ge=0, le=100)
    loan_pct: int | None = Field(default=None, ge=0, le=100)
    work_pct: int | None = Field(default=None, ge=0, le=100)
    source_url: HttpUrl
    year: int = Field(ge=2000, le=2100)
    note: str | None = None


class Deadline(_Model):
    """An application deadline for one plan and cycle."""

    plan: DeadlinePlan
    date: dt.date | None = None
    cycle: str = Field(pattern=r"^\d{4}-\d{2}$")
    source_url: HttpUrl | None = None
    note: str | None = None


class Scholarship(_Model):
    """A scholarship of one institution."""

    name: str
    amount: str | None = None
    deadline: dt.date | None = None
    url: HttpUrl
    year: int | None = Field(default=None, ge=2000, le=2100)


class Aid(_Model):
    """Financial aid facts."""

    basis: Fact = Fact()  # value: AidBasis
    merit_for_internationals: Fact = Fact()  # value: bool
    meets_full_need: Fact = Fact()  # value: bool
    avg_aid: AvgAid | None = None


class Safety(_Model):
    """Safety facts."""

    crime_index: Fact = Fact()


class Description(_Model):
    """A short description of an institution in each interface language."""

    en: str = Field(max_length=400)
    ru: str = Field(max_length=400)
    uz: str = Field(max_length=400)


def slug_from_domain(domain: str) -> str:
    """The default slug of an entry that has only a website domain."""
    d = domain.strip().lower().removeprefix("www.")
    return re.sub(r"[^a-z0-9]+", "-", d).strip("-")


class Institution(_Model):
    """A university with its sourced facts.

    ``slug`` may be omitted when ``website_domain`` is set (enrichment files); it
    then defaults to the domain with dots turned into hyphens.
    """

    slug: str = Field(default="", pattern=r"^([a-z0-9-]+)?$")
    name: str
    country: str = Field(pattern=r"^[A-Z]{2}$")
    city: str
    website_domain: str | None = None
    description: Description | None = None
    city_type: CityType | None = None
    institution_type: Literal["public", "private"] | None = None
    fields: list[str] = []
    acceptance_rate: RangeFact | None = None  # percent
    intl_acceptance_rate: Fact | None = None  # value: percent
    test_policy: Fact | None = None  # value: TestPolicy
    focuses: Fact | None = None  # value: list of focus items (see domain/focuses)
    intl_tuition_usd: Money | None = None
    intl_coa_usd: Money | None = None
    aid: Aid = Aid()
    scholarships: list[Scholarship] = []
    deadlines: list[Deadline] = []
    safety: Safety = Safety()
    source_url: HttpUrl
    year: int = Field(ge=2000, le=2100)
    verified: bool = False

    @model_validator(mode="after")
    def _default_slug(self) -> "Institution":
        if not self.slug:
            if not self.website_domain:
                raise ValueError("slug or website_domain is required")
            self.slug = slug_from_domain(self.website_domain)
        return self


class Program(_Model):
    """National scholarship programme (not tied to one institution)."""

    name: str
    country: str = Field(pattern=r"^[A-Z]{2}$")
    level: str
    coverage: str | None = None
    deadline: dt.date | None = None
    url: HttpUrl
    year: int = Field(ge=2000, le=2100)
    note: str | None = None
    verified: bool = False


class Seed(_Model):
    """One seed file: institutions and national programmes."""

    institutions: list[Institution] = []
    programs: list[Program] = []


def _read_all() -> list[Seed]:
    return [
        Seed.model_validate(json.loads(p.read_text("utf-8")))
        for p in [
            *sorted(_DIR.glob("*.json")),
            *sorted((_DIR / "enrich").glob("*.json")),
        ]
    ]


def enrich_slugs() -> set[str]:
    """Slugs of the entries that come from ``enrich/*.json``."""
    return {
        i.slug
        for p in (_DIR / "enrich").glob("*.json")
        for i in Seed.model_validate(json.loads(p.read_text("utf-8"))).institutions
    }


def load_seed() -> list[dict[str, Any]]:
    """All institutions of ``*.json`` and ``enrich/*.json``, validated, as dicts.

    ``PROFILES`` adds the city type, institution type and demo media by slug.
    """
    return [
        {**i.model_dump(mode="json"), **PROFILES.get(i.slug, {})}
        for seed in _read_all()
        for i in seed.institutions
    ]


def load_programs() -> list[dict[str, Any]]:
    """All national programmes of ``*.json`` and ``enrich/*.json``, validated."""
    return [p.model_dump(mode="json") for seed in _read_all() for p in seed.programs]


def study_fields() -> tuple[str, ...]:
    """Fields of study of the seed catalog, merged to canonical names."""
    return tuple(canonical_names([n for inst in load_seed() for n in inst["fields"]]))
