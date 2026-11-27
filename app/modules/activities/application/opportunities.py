"""Staff management and audience-filtered reading of the one opportunities catalog."""

from typing import Any
from uuid import UUID

from app.modules.activities.domain.errors import ActivitiesNotFoundError, Denied
from app.modules.activities.ports.bundle import Ports
from app.modules.activities.ports.gateways import CatalogEntry
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    CatalogInUseError,
    InvalidProofUrlError,
)
from app.modules.admission.domain.opportunities import OpportunityDraft
from app.modules.admission.domain.urls import is_https_url
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError

SURFACES = frozenset({"admission", "my_iht"})
_CURATORS = frozenset({Role.ADMIN, Role.ACTIVITIES_ADMIN})


class CatalogDeniedError(Denied):
    """Only administrators and activities administrators manage the catalog."""


def _curator(actor: Actor) -> bool:
    return bool(actor.roles & _CURATORS)


def _require(actor: Actor) -> None:
    if not _curator(actor):
        raise CatalogDeniedError()


def _surface(surface: str) -> str:
    if surface not in SURFACES:
        raise ValidationFailedError(params={"field": "surface"})
    return surface


class OpportunitiesService:
    """One catalog shared by admission and my.iht, with the audience on each entry."""

    def __init__(self, p: Ports) -> None:
        """Keep the ports."""
        self._p = p

    async def _checked(self, draft: OpportunityDraft, audience: frozenset[str]) -> None:
        bad = draft.problems()
        if bad:
            raise ValidationFailedError(params={"field": bad[0]})
        if not all(is_https_url(u) for u in draft.urls()):
            raise InvalidProofUrlError()
        if not audience or not audience <= SURFACES:
            raise ValidationFailedError(params={"field": "audience"})
        ref = await self._p.catalog.references_ok(draft)
        if ref is not None:
            raise ValidationFailedError(params={"field": ref})

    async def _entry(self, opportunity_id: UUID) -> CatalogEntry:
        entry = await self._p.catalog.get(opportunity_id)
        if entry is None:
            raise ActivitiesNotFoundError()
        return entry

    async def create(
        self,
        actor: Actor,
        kind: str,
        title: str,
        audience: frozenset[str],
        **fields: Any,
    ) -> CatalogEntry:
        """Publish an entry; admission's validation applies."""
        _require(actor)
        draft = OpportunityDraft(
            kind=kind, title=title, **fields  # type: ignore[arg-type]
        )
        await self._checked(draft, audience)
        new_id = await self._p.catalog.apply(
            draft, frozenset(audience), target_id=None, by=actor.user_id
        )
        await self._p.audit.record(actor.user_id, "opportunity.staff_created", new_id)
        return await self._entry(new_id)

    async def update(
        self,
        actor: Actor,
        opportunity_id: UUID,
        kind: str,
        title: str,
        audience: frozenset[str],
        *,
        lock_version: int,
        **fields: Any,
    ) -> CatalogEntry:
        """Overwrite an entry; a stale `lock_version` conflicts."""
        _require(actor)
        current = await self._entry(opportunity_id)
        if current.lock_version != lock_version:
            raise AdmissionConflictError()
        draft = OpportunityDraft(
            kind=kind, title=title, **fields  # type: ignore[arg-type]
        )
        await self._checked(draft, audience)
        await self._p.catalog.apply(
            draft, frozenset(audience), target_id=opportunity_id, by=actor.user_id
        )
        await self._p.audit.record(
            actor.user_id, "opportunity.staff_edited", opportunity_id
        )
        return await self._entry(opportunity_id)

    async def archive(
        self, actor: Actor, opportunity_id: UUID, archived: bool
    ) -> CatalogEntry:
        """Hide an entry everywhere or bring it back."""
        _require(actor)
        await self._entry(opportunity_id)
        await self._p.catalog.set_archived(opportunity_id, archived)
        action = "opportunity.archived" if archived else "opportunity.restored"
        await self._p.audit.record(actor.user_id, action, opportunity_id)
        return await self._entry(opportunity_id)

    async def delete(self, actor: Actor, opportunity_id: UUID) -> None:
        """Delete an unused entry; otherwise `CatalogInUseError`."""
        _require(actor)
        await self._entry(opportunity_id)
        if await self._p.catalog.in_use(
            opportunity_id
        ) or await self._p.events.references_opportunity(opportunity_id):
            raise CatalogInUseError(params={"kind": "opportunity"})
        await self._p.catalog.delete(opportunity_id)
        await self._p.audit.record(
            actor.user_id, "opportunity.staff_deleted", opportunity_id
        )

    def _visible(self, actor: Actor, entry: CatalogEntry, surface: str) -> bool:
        if surface not in entry.audience:
            return False
        return _curator(actor) or not entry.archived

    async def list(self, actor: Actor, surface: str) -> list[CatalogEntry]:
        """Entries shown on the surface; archived ones only to curators."""
        _surface(surface)
        return [
            e
            for e in await self._p.catalog.list_all()
            if self._visible(actor, e, surface)
        ]

    async def get(
        self, actor: Actor, opportunity_id: UUID, surface: str
    ) -> CatalogEntry:
        """One entry; an entry outside the audience is 404, never 403."""
        _surface(surface)
        entry = await self._entry(opportunity_id)
        if not self._visible(actor, entry, surface):
            raise ActivitiesNotFoundError()
        return entry
