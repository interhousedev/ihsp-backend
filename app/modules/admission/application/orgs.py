"""Organizations that tag opportunities and scholarships (staff-managed)."""

import dataclasses
from collections.abc import Sequence
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.opportunities import OpportunityService
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.orgs import Organization, OrgKind
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.ids import new_id


class OrgService:
    """Lists organizations for everyone; moderators create, edit and delete."""

    def __init__(
        self,
        uow_factory: UowFactory,
        opportunities: OpportunityService,
        clock: Clock,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._opps = opportunities
        self._clock = clock

    def _require(self, ctx: AdmissionContext) -> None:
        if not self._opps.can_moderate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": "opportunities:moderate"}
            )

    async def list(self) -> list[Organization]:
        """Every organization ordered by name."""
        async with self._uow() as uow:
            return await uow.orgs.list()

    async def get(self, org_id: UUID) -> Organization:
        """One organization."""
        async with self._uow() as uow:
            org = await uow.orgs.get(org_id)
        if org is None:
            raise AdmissionNotFoundError()
        return org

    async def exists(self, org_id: UUID) -> bool:
        """Return whether the organization exists."""
        async with self._uow() as uow:
            return await uow.orgs.get(org_id) is not None

    async def by_ids(self, org_ids: Sequence[UUID]) -> dict[UUID, Organization]:
        """The organizations among `org_ids`."""
        async with self._uow() as uow:
            return await uow.orgs.by_ids(list(org_ids))

    async def create(
        self,
        ctx: AdmissionContext,
        *,
        name: str,
        kind: OrgKind,
        logo_url: str | None = None,
        logo_zoom: float = 1.0,
        website: str | None = None,
        country: str | None = None,
    ) -> Organization:
        """Create an organization."""
        self._require(ctx)
        now = self._clock.now()
        org = Organization(
            id=new_id(),
            name=name,
            kind=kind,
            created_at=now,
            updated_at=now,
            logo_url=logo_url,
            logo_zoom=logo_zoom,
            website=website,
            country=country,
        )
        self._validate(org)
        async with self._uow() as uow:
            saved = await uow.orgs.save(org)
            await uow.commit()
        return saved

    async def update(
        self, ctx: AdmissionContext, org_id: UUID, **changes: object
    ) -> Organization:
        """Overwrite the given fields of an organization."""
        self._require(ctx)
        async with self._uow() as uow:
            current = await uow.orgs.get(org_id)
            if current is None:
                raise AdmissionNotFoundError()
            org = dataclasses.replace(current, **changes)  # type: ignore[arg-type]
            self._validate(org)
            saved = await uow.orgs.save(org)
            await uow.commit()
        return saved

    async def delete(self, ctx: AdmissionContext, org_id: UUID) -> None:
        """Delete an organization no entry refers to."""
        self._require(ctx)
        async with self._uow() as uow:
            if await uow.orgs.get(org_id) is None:
                raise AdmissionNotFoundError()
            for entry in await uow.opportunities.list_published():
                if entry.draft.org_id == org_id:
                    raise AdmissionConflictError()
            await uow.orgs.delete(org_id)
            await uow.commit()

    @staticmethod
    def _validate(org: Organization) -> None:
        bad = org.problems()
        if bad:
            raise ValidationFailedError(params={"field": bad[0]})
