"""Request and response shapes of the country facts routes."""

import datetime as dt
from typing import Annotated, Literal

from app.modules.admission.application.country_facts import CountrySummary
from app.modules.admission.domain.country_facts import CountryFacts

from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr

FactValue = StrictBool | StrictInt | StrictFloat | StrictStr
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
    values: dict[str, FactValue] = Field(default_factory=dict)
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
