"""Seed catalog of universities popular with Uzbek applicants.

Every fact carries ``source_url`` and ``year``; anything not verified is ``None``
(never guessed). ``load_seed()`` validates the JSON files against the pydantic
schema below and returns plain dicts of the same shape the importers produce.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Literal

from app.modules.admission.domain.study_fields import canonical_names
from app.modules.admission.infrastructure.catalog_data.profiles import PROFILES

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

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


class Safety(_Model):
    """Safety facts."""

    crime_index: Fact = Fact()


class Institution(_Model):
    """A university with its sourced facts."""

    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    country: str = Field(pattern=r"^[A-Z]{2}$")
    city: str
    city_type: CityType | None = None
    fields: list[str] = []
    acceptance_rate: RangeFact | None = None  # percent
    test_policy: Fact | None = None  # value: TestPolicy
    intl_tuition_usd: Money | None = None
    intl_coa_usd: Money | None = None
    aid: Aid = Aid()
    scholarships: list[Scholarship] = []
    deadlines: list[Deadline] = []
    safety: Safety = Safety()
    source_url: HttpUrl
    year: int = Field(ge=2000, le=2100)
    verified: bool = False


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
        for p in sorted(_DIR.glob("*.json"))
    ]


def load_seed() -> list[dict[str, Any]]:
    """All institutions from every ``*.json`` file, validated, as plain dicts.

    ``PROFILES`` adds the city type, institution type and demo media by slug.
    """
    return [
        {**i.model_dump(mode="json"), **PROFILES.get(i.slug, {})}
        for seed in _read_all()
        for i in seed.institutions
    ]


def load_programs() -> list[dict[str, Any]]:
    """All national programmes from every ``*.json`` file, validated."""
    return [p.model_dump(mode="json") for seed in _read_all() for p in seed.programs]


def study_fields() -> tuple[str, ...]:
    """Fields of study of the seed catalog, merged to canonical names."""
    return tuple(canonical_names([n for inst in load_seed() for n in inst["fields"]]))
