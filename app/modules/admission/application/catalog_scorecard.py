"""Curators fill a US institution from the College Scorecard."""

from collections.abc import Callable
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.scorecard import ScorecardClient, ScorecardSchool
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock

SOURCE_URL = "https://collegescorecard.ed.gov/school/?{unitid}"
QUERY_MIN = 2


class CatalogScorecardService:
    """Search the Scorecard and attach a school's facts to an institution."""

    def __init__(
        self,
        uow_factory: UowFactory,
        client: ScorecardClient,
        can_curate: Callable[[AdmissionContext], bool],
        clock: Clock,
    ) -> None:
        """Keep the transaction factory, the Scorecard client, curator rule, clock."""
        self._uow = uow_factory
        self._client = client
        self._can_curate = can_curate
        self._clock = clock

    def _require_curator(self, ctx: AdmissionContext) -> None:
        if not self._can_curate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.CATALOG_CURATE.value}
            )

    async def search(self, ctx: AdmissionContext, query: str) -> list[ScorecardSchool]:
        """Schools by name, or the one school of a numeric `UNITID`."""
        self._require_curator(ctx)
        text = query.strip()
        if len(text) < QUERY_MIN and not text.isdigit():
            raise ValidationFailedError(params={"field": "q"})
        if text.isdigit():
            one = await self._client.get(int(text))
            return [one] if one is not None else []
        return await self._client.search(text)

    async def attach(
        self, ctx: AdmissionContext, institution_id: UUID, unitid: int
    ) -> ScorecardSchool:
        """Upsert the school's facts with their source; fill an empty website."""
        self._require_curator(ctx)
        school = await self._client.get(unitid)
        if school is None:
            raise AdmissionNotFoundError()
        now = self._clock.now()
        source = SOURCE_URL.format(unitid=unitid)
        facts = {
            key: {"value": value, "source_url": source, "year": now.year, "note": None}
            for key, value in school.facts.items()
        }
        async with self._uow() as uow:
            inst = await uow.catalog_staff.get_institution(institution_id)
            if inst is None:
                raise AdmissionNotFoundError()
            if inst.country != "US":
                raise ValidationFailedError(params={"field": "country"})
            await uow.catalog_proposals.apply_facts(
                institution_id, facts, ctx.user_id, now
            )
            if inst.website_domain is None and school.website_domain:
                await uow.catalog_staff.update_institution(
                    institution_id,
                    {"website_domain": school.website_domain},
                    expected_lock=inst.lock_version,
                )
            uow.access.audit(
                AuditEvent(
                    action="catalog.scorecard_attached",
                    actor_id=ctx.user_id,
                    student_id=None,
                    object_type="catalog_institution",
                    object_id=institution_id,
                    meta={"unitid": unitid, "facts": sorted(facts)},
                )
            )
            await uow.commit()
        return school
