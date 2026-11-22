"""Country facts: students read them, curators list, edit and verify them."""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.countries import COUNTRIES
from app.modules.admission.domain.country_facts import (
    COUNTRY_STATUSES,
    CountryFacts,
    clean_as_of,
    clean_facts,
    coverage,
    is_country,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.country_facts import CountryFactsRepository
from app.shared.base_error import ValidationFailedError

CanCurate = Callable[[AdmissionContext], bool]
READ_MAX = 30
"""Most countries one read may name."""


@dataclass(frozen=True, slots=True)
class CountrySummary:
    """One line of the staff country list."""

    country: str
    status: str
    """`missing` (no row), `draft` or `verified`."""
    coverage: int
    as_of: str | None
    updated_at: dt.datetime | None


class CountryFactsService:
    """Read, list, edit and verify the facts of countries."""

    def __init__(self, repo: CountryFactsRepository, can_curate: CanCurate) -> None:
        """Keep the storage and the curator rule."""
        self._repo = repo
        self._can_curate = can_curate

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
