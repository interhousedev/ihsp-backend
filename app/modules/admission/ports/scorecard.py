"""Port: the US College Scorecard, a public dataset of American colleges."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ScorecardSchool:
    """One school: identity plus catalog facts in the shape `clean_facts` takes."""

    unitid: int
    name: str
    city: str | None
    state: str | None
    website_domain: str | None
    facts: dict[str, Any] = field(default_factory=dict)
    """`{fact key: value}`, e.g. `acceptance_rate` -> `{"min": 4.2, "max": 4.2}`."""


class ScorecardClient(Protocol):
    """Looks schools up by name or by `UNITID`."""

    async def search(self, query: str) -> list[ScorecardSchool]:
        """Return up to ten matches; raises `ScorecardUnavailableError` on failure."""
        ...

    async def get(self, unitid: int) -> ScorecardSchool | None:
        """Return one school or None; raises `ScorecardUnavailableError` on failure."""
        ...
