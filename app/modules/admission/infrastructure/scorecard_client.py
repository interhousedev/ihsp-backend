"""HTTP client of the College Scorecard API (reuses the importer's parsing)."""

from typing import Any
from urllib.parse import urlsplit

from app.modules.admission.domain.errors import ScorecardUnavailableError
from app.modules.admission.infrastructure.importers.scorecard import (
    API_URL,
    FIELDS,
    parse_school,
    search_params,
)
from app.modules.admission.ports.scorecard import ScorecardSchool

import httpx

TIMEOUT_SECONDS = 10.0
PER_PAGE = "10"


def _domain(url: str) -> str | None:
    host = urlsplit(url).hostname or ""
    host = host.removeprefix("www.")
    return host or None


def school_of(row: dict[str, Any], year: int) -> ScorecardSchool:
    """One flat API record to a `ScorecardSchool` with its clean fact values."""
    parsed = parse_school(row, year)
    facts: dict[str, Any] = {}
    rate = parsed["acceptance_rate"]
    if rate is not None:
        facts["acceptance_rate"] = {"min": rate["min"], "max": rate["max"]}
    policy = parsed["test_policy"]
    if policy is not None and policy["value"] is not None:
        facts["test_policy"] = policy["value"]
    for key in ("intl_tuition_usd", "intl_coa_usd"):
        item = parsed[key]
        if item is not None:
            facts[key] = {"amount": item["value"], "currency": "USD"}
    url = str(row.get("school.school_url") or "")
    web = url if url.startswith("http") else f"https://{url}" if url else ""
    state = row.get("school.state")
    city = row.get("school.city")
    return ScorecardSchool(
        unitid=int(row["id"]),
        name=str(row["school.name"]),
        city=str(city) if city else None,
        state=str(state) if state else None,
        website_domain=_domain(web) if web else None,
        facts=facts,
    )


class HttpScorecardClient:
    """Name and `UNITID` lookups against `api.data.gov/ed/collegescorecard`."""

    def __init__(
        self,
        api_key: str | None,
        year: int,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """`year` stamps the facts; `transport` is for tests."""
        self._key = api_key or None
        self._year = year
        self._transport = transport

    async def search(self, query: str) -> list[ScorecardSchool]:
        """Up to ten schools whose name matches."""
        params = search_params(query, self._key)
        params["per_page"] = PER_PAGE
        return await self._fetch(params)

    async def get(self, unitid: int) -> ScorecardSchool | None:
        """The school with this `UNITID`."""
        params = {
            "api_key": self._key or "DEMO_KEY",
            "id": str(unitid),
            "fields": FIELDS,
        }
        found = await self._fetch(params)
        return found[0] if found else None

    async def _fetch(self, params: dict[str, str]) -> list[ScorecardSchool]:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(TIMEOUT_SECONDS), transport=self._transport
            ) as client:
                response = await client.get(API_URL, params=params)
            response.raise_for_status()
            rows = response.json().get("results", [])
            return [
                school_of(r, self._year)
                for r in rows
                if r.get("school.name") and "id" in r
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as e:
            raise ScorecardUnavailableError() from e
