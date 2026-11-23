"""Country facts: students read them, curators list, edit and verify them."""

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.countries import COUNTRIES
from app.modules.admission.domain.country_facts import (
    COUNTRY_STATUSES,
    REGION_OF,
    CountryFacts,
    clean_as_of,
    clean_facts,
    coverage,
    is_country,
    opportunity_fields_of,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.rankings import relevant_rankings, subjects_for
from app.modules.admission.domain.study_fields import canonical_id
from app.modules.admission.ports.country_facts import CountryFactsRepository
from app.shared.base_error import ValidationFailedError

CanCurate = Callable[[AdmissionContext], bool]
InstitutionsOf = Callable[[str | None], Awaitable[list[CatalogInstitution]]]
"""Non-archived catalog institutions, of one country or (None) of all."""
READ_MAX = 30
"""Most countries one read may name."""
PROFILE_INSTITUTIONS_MAX = 60
"""Most institutions one country profile lists, best ranked first."""


@dataclass(frozen=True, slots=True)
class CountrySummary:
    """One line of the staff country list."""

    country: str
    status: str
    """`missing` (no row), `draft` or `verified`."""
    coverage: int
    as_of: str | None
    updated_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class CountryOverview:
    """One card of the student country list."""

    country: str
    region: str
    status: str
    """`missing` (no facts yet), `draft` or `verified`."""
    coverage: int
    as_of: str | None
    scores: dict[str, int]
    """Fact key → its 1-5 score, only the scored facts."""
    institution_count: int
    median_salary_usd: float | None


@dataclass(frozen=True, slots=True)
class CountryInstitution:
    """A catalog institution of a country with its rankings worth showing."""

    institution: CatalogInstitution
    rankings: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CountryProfile:
    """Everything the student country page shows."""

    country: str
    region: str
    facts: CountryFacts | None
    highlight: list[str]
    institutions: list[CountryInstitution]
    institution_count: int


class CountryFactsService:
    """Read, list, edit and verify the facts of countries."""

    def __init__(
        self,
        repo: CountryFactsRepository,
        can_curate: CanCurate,
        institutions: InstitutionsOf,
    ) -> None:
        """Keep the storage, the curator rule and the catalog reader."""
        self._repo = repo
        self._can_curate = can_curate
        self._institutions = institutions

    def _require_curator(self, ctx: AdmissionContext) -> None:
        if not self._can_curate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.CATALOG_CURATE.value}
            )

    @staticmethod
    def _code(raw: str) -> str:
        code = raw.strip().upper()
        if not is_country(code):
            raise AdmissionNotFoundError()
        return code

    async def read(self, codes: list[str]) -> list[CountryFacts]:
        """The facts of the named countries (those without facts are left out)."""
        wanted = list(dict.fromkeys(self._code(c) for c in codes))
        if len(wanted) > READ_MAX:
            raise ValidationFailedError(params={"field": "codes"})
        return await self._repo.get_many(wanted)

    async def read_one(self, code: str) -> CountryFacts:
        """The facts of one country; 404 when it has none yet."""
        found = await self._repo.get_many([self._code(code)])
        if not found:
            raise AdmissionNotFoundError()
        return found[0]

    async def overview(self) -> list[CountryOverview]:
        """Countries with facts or catalog institutions, by ISO code."""
        stored = {r.country: r for r in await self._repo.list_all()}
        counts: dict[str, int] = {}
        for inst in await self._institutions(None):
            code = inst.country.upper()
            counts[code] = counts.get(code, 0) + 1
        out: list[CountryOverview] = []
        for code in COUNTRIES:
            row = stored.get(code)
            if row is None and code not in counts:
                continue
            facts = row.facts if row else {}
            out.append(
                CountryOverview(
                    country=code,
                    region=REGION_OF.get(code, "other"),
                    status=row.status if row else "missing",
                    coverage=coverage(facts),
                    as_of=row.as_of if row else None,
                    scores={k: f["score"] for k, f in facts.items() if f.get("score")},
                    institution_count=counts.get(code, 0),
                    median_salary_usd=_median_salary(facts),
                )
            )
        return out

    async def profile(self, code: str, fields: list[str]) -> CountryProfile:
        """Facts, region and ranked institutions of one country (facts may be None)."""
        code = self._code(code)
        found = await self._repo.get_many([code])
        institutions = await self._institutions(code)
        subjects = subjects_for(canonical_id(f) for f in fields)
        ranked = [
            CountryInstitution(i, relevant_rankings(_rankings(i), subjects))
            for i in institutions
        ]
        ranked.sort(key=lambda r: (_best_rank(r.rankings), r.institution.name))
        return CountryProfile(
            country=code,
            region=REGION_OF.get(code, "other"),
            facts=found[0] if found else None,
            highlight=opportunity_fields_of(fields),
            institutions=ranked[:PROFILE_INSTITUTIONS_MAX],
            institution_count=len(institutions),
        )

    async def summaries(
        self,
        ctx: AdmissionContext,
        *,
        query: str | None,
        status: str | None,
    ) -> list[CountrySummary]:
        """Every offered country with its coverage; `status` may be `missing`."""
        self._require_curator(ctx)
        if status is not None and status not in (*COUNTRY_STATUSES, "missing"):
            raise ValidationFailedError(params={"field": "status"})
        stored = {r.country: r for r in await self._repo.list_all()}
        needle = (query or "").strip().casefold()
        out: list[CountrySummary] = []
        for code in COUNTRIES:
            if needle and needle not in code.casefold():
                continue
            row = stored.get(code)
            line = CountrySummary(
                country=code,
                status=row.status if row else "missing",
                coverage=coverage(row.facts) if row else 0,
                as_of=row.as_of if row else None,
                updated_at=row.updated_at if row else None,
            )
            if status is None or line.status == status:
                out.append(line)
        return out

    async def save(
        self,
        ctx: AdmissionContext,
        code: str,
        *,
        as_of: str,
        facts: dict[str, Any],
        verified: bool,
    ) -> CountryFacts:
        """Replace the facts of a country as the caller's edit."""
        self._require_curator(ctx)
        return await self._repo.save(
            self._code(code),
            as_of=clean_as_of(as_of),
            facts=clean_facts(facts),
            editor=_editor(ctx),
            verified=verified,
        )

    async def verify(self, ctx: AdmissionContext, code: str) -> CountryFacts:
        """Mark the stored facts of a country verified."""
        self._require_curator(ctx)
        done = await self._repo.set_verified(self._code(code), _editor(ctx))
        if done is None:
            raise AdmissionNotFoundError()
        return done


def _editor(ctx: AdmissionContext) -> UUID:
    return ctx.actor.user_id


def _median_salary(facts: dict[str, dict[str, Any]]) -> float | None:
    value = facts.get("salaries", {}).get("values", {}).get("overall_median_annual")
    return float(value) if isinstance(value, int | float) else None


def _rankings(inst: CatalogInstitution) -> Any:
    fact = inst.fact("rankings")
    return fact.value if fact is not None else None


def _best_rank(rankings: list[dict[str, Any]]) -> float:
    """The overall rank (a band counts by its lower bound); unranked last."""
    for item in rankings:
        if item.get("subject") != "overall":
            continue
        rank = item.get("rank")
        if isinstance(rank, int):
            return float(rank)
        if isinstance(rank, str) and rank.split("-")[0].isdigit():
            return float(rank.split("-")[0])
    return float("inf")
