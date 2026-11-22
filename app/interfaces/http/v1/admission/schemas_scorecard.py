"""Schemas of the College Scorecard lookup of the staff catalog."""

from typing import Any

from app.modules.admission.ports.scorecard import ScorecardSchool

from pydantic import BaseModel, Field


class ScorecardSchoolOut(BaseModel):
    """A Scorecard school with the facts it would fill."""

    unitid: int
    name: str
    city: str | None
    state: str | None
    website_domain: str | None
    facts: dict[str, Any] = Field(
        description="Fact key to value, e.g. `acceptance_rate` {min, max}."
    )

    @classmethod
    def of(cls, school: ScorecardSchool) -> "ScorecardSchoolOut":
        """Build from the port record."""
        return cls(
            unitid=school.unitid,
            name=school.name,
            city=school.city,
            state=school.state,
            website_domain=school.website_domain,
            facts=school.facts,
        )


class ScorecardSearchOut(BaseModel):
    """Up to ten candidates."""

    items: list[ScorecardSchoolOut]


class ScorecardAttachIn(BaseModel):
    """The Scorecard `UNITID` to attach."""

    unitid: int = Field(ge=1, le=99_999_999)
