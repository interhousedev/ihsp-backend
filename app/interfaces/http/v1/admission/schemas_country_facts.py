"""Request and response shapes of the country facts routes."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.media import served_media
from app.modules.admission.application.country_facts import (
    CountryInstitution,
    CountryOverview,
    CountryProfile,
    CountrySummary,
)
from app.modules.admission.domain.country_facts import CountryFacts

from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr

FactValue = StrictBool | StrictInt | StrictFloat | StrictStr
Amount = StrictInt | StrictFloat


class EmployerOut(BaseModel):
    """A notable employer of a field (`employers.values.fields.<field>[]`)."""

    name: str
    sector: str | None = None
    url: str | None = None


FactValues = dict[
    str, FactValue | dict[str, list[EmployerOut]] | dict[str, Amount] | None
]
"""Flat values; `employers.fields` and `salaries.by_field` nest one level."""
Score = Annotated[int, Field(ge=1, le=5)] | None
AsOf = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class FactText(BaseModel):
    """A fact's description in the three languages (a missing one is empty)."""

    en: str = ""
    ru: str = ""
    uz: str = ""


class CountryFactBody(BaseModel):
    """One fact: a 1-5 score (5 is best for the student), values, text, sources."""

    score: Score = None
    values: FactValues = Field(default_factory=dict)
    text: FactText = Field(default_factory=FactText)
    sources: list[str] = Field(default_factory=list)


class CountryFactsOut(BaseModel):
    """The facts of one country."""

    country: str
    as_of: str
    status: Literal["draft", "verified"]
    verified: bool
    facts: dict[str, CountryFactBody]
    updated_at: dt.datetime | None

    @classmethod
    def of(cls, row: CountryFacts) -> "CountryFactsOut":
        """Project a stored row."""
        return cls(
            country=row.country,
            as_of=row.as_of,
            status=row.status,
            verified=row.status == "verified",
            facts={k: CountryFactBody.model_validate(v) for k, v in row.facts.items()},
            updated_at=row.updated_at,
        )


class CountryFactsListOut(BaseModel):
    """Facts of several countries; a country without facts is absent."""

    items: list[CountryFactsOut]
    highlight: list[str] = Field(default_factory=list)
    """`opportunities.values` keys of the student's own study fields."""


class CountryFactsPutIn(BaseModel):
    """A curator's replacement of a country's facts."""

    as_of: AsOf
    facts: dict[str, CountryFactBody]
    verified: bool = False


class CountrySummaryOut(BaseModel):
    """One line of the staff country list."""

    country: str
    status: Literal["missing", "draft", "verified"]
    coverage: int
    as_of: str | None
    updated_at: dt.datetime | None

    @classmethod
    def of(cls, s: CountrySummary) -> "CountrySummaryOut":
        """Project a summary."""
        return cls(
            country=s.country,
            status=s.status,
            coverage=s.coverage,
            as_of=s.as_of,
            updated_at=s.updated_at,
        )


class CountrySummaryListOut(BaseModel):
    """Every country with its coverage."""

    items: list[CountrySummaryOut]


class CountryOverviewOut(BaseModel):
    """One card of the student country list."""

    country: str
    region: str
    status: Literal["missing", "draft", "verified"]
    coverage: int
    as_of: str | None
    scores: dict[str, int]
    institution_count: int
    median_salary_usd: float | None

    @classmethod
    def of(cls, o: CountryOverview) -> "CountryOverviewOut":
        """Project an overview line."""
        return cls(
            country=o.country,
            region=o.region,
            status=o.status,
            coverage=o.coverage,
            as_of=o.as_of,
            scores=o.scores,
            institution_count=o.institution_count,
            median_salary_usd=o.median_salary_usd,
        )


class CountryOverviewListOut(BaseModel):
    """Countries with facts or catalog institutions."""

    items: list[CountryOverviewOut]


class CountryRankingOut(BaseModel):
    """One ranking of an institution (`overall` or a subject)."""

    system: str
    subject: str
    rank: int | str
    year: int | None = None


class CountryInstitutionOut(BaseModel):
    """A catalog institution of the country."""

    id: UUID
    name: str
    city: str | None
    logo_url: str | None
    verified: bool
    rankings: list[CountryRankingOut]

    @classmethod
    def of(cls, c: CountryInstitution) -> "CountryInstitutionOut":
        """Project an institution with its rankings."""
        i = c.institution
        return cls(
            id=i.id,
            name=i.name,
            city=i.city,
            logo_url=served_media(i.logo_url),
            verified=i.verified,
            rankings=[CountryRankingOut.model_validate(r) for r in c.rankings],
        )


class CountryProfileOut(BaseModel):
    """The student country page: facts (null when none yet) and institutions."""

    country: str
    region: str
    facts: CountryFactsOut | None
    highlight: list[str]
    """Opportunity field keys of the student's own study fields."""
    institutions: list[CountryInstitutionOut]
    institution_count: int

    @classmethod
    def of(cls, p: CountryProfile) -> "CountryProfileOut":
        """Project a profile."""
        return cls(
            country=p.country,
            region=p.region,
            facts=CountryFactsOut.of(p.facts) if p.facts else None,
            highlight=p.highlight,
            institutions=[CountryInstitutionOut.of(c) for c in p.institutions],
            institution_count=p.institution_count,
        )
