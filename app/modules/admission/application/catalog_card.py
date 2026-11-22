"""Direct curator editing of an institution's facts, scholarships, description."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.catalog_card import (
    SCHOLARSHIP_WRITE,
    CardFact,
    clean_description,
)
from app.modules.admission.domain.catalog_proposals import invalid_field
from app.modules.admission.domain.chooser import CatalogScholarship
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.intl_facts import FACT_SPECS, clean_facts
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock

CanCurate = Callable[[AdmissionContext], bool]


@dataclass(frozen=True, slots=True)
class Card:
    """Everything a curator edits on one institution."""

    lock_version: int
    facts: list[CardFact]
    scholarships: list[CatalogScholarship]
    description: dict[str, str] | None


def _scholarship_values(raw: Mapping[str, Any], *, create: bool) -> dict[str, Any]:
    values = {k: v for k, v in raw.items() if k in SCHOLARSHIP_WRITE}
    if create and not all(values.get(k) for k in ("name", "provider", "basis")):
        raise ValidationFailedError(params={"field": "name"})
    bad = invalid_field("scholarship", values)
    if bad is not None:
        raise ValidationFailedError(params={"field": bad})
    lo, hi = values.get("coverage_pct_min"), values.get("coverage_pct_max")
    if lo is not None and hi is not None and lo > hi:
        raise ValidationFailedError(params={"field": "coverage_pct_min"})
    return values


class CatalogCardService:
    """Administrators and counselors edit one institution's card in place."""

    def __init__(
        self, uow_factory: UowFactory, can_curate: CanCurate, clock: Clock
    ) -> None:
        """Keep the transaction factory, the curator rule and the clock."""
        self._uow = uow_factory
        self._can_curate = can_curate
        self._clock = clock

    def _require(self, ctx: AdmissionContext) -> None:
        if not self._can_curate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.CATALOG_CURATE.value}
            )

    @staticmethod
    def _audit(
        uow: AdmissionUnitOfWork,
        ctx: AdmissionContext,
        action: str,
        oid: UUID,
        **meta: Any,
    ) -> None:
        uow.access.audit(
            AuditEvent(
                action=action,
                actor_id=ctx.user_id,
                student_id=None,
                object_type="catalog_institution",
                object_id=oid,
                meta=meta,
            )
        )

    @staticmethod
    async def _bump(uow: AdmissionUnitOfWork, iid: UUID, lock: int) -> int:
        """Move the institution's optimistic lock; a stale one conflicts."""
        if not await uow.catalog_staff.update_institution(iid, {}, expected_lock=lock):
            raise AdmissionNotFoundError()
        saved = await uow.catalog_staff.get_institution(iid)
        if saved is None:
            raise AdmissionNotFoundError()
        return saved.lock_version

    async def get(self, ctx: AdmissionContext, iid: UUID) -> Card:
        """Facts, scholarships, description and the lock to send back."""
        self._require(ctx)
        async with self._uow() as uow:
            inst = await uow.catalog_staff.get_institution(iid)
            if inst is None:
                raise AdmissionNotFoundError()
            return Card(
                inst.lock_version,
                await uow.catalog_card.facts(iid),
                await uow.catalog_card.scholarships(iid),
                await uow.catalog_card.description(iid),
            )

    async def save_facts(
        self,
        ctx: AdmissionContext,
        iid: UUID,
        facts: Mapping[str, Mapping[str, Any]],
        remove: list[str],
        *,
        lock_version: int,
    ) -> int:
        """Upsert and delete facts; `verified` false leaves a fact unreviewed."""
        self._require(ctx)
        if not facts and not remove:
            raise ValidationFailedError(params={"field": "facts"})
        for key in remove:
            if key not in FACT_SPECS:
                raise ValidationFailedError(params={"field": key})
        payload = {
            k: {a: b for a, b in v.items() if a != "verified"} for k, v in facts.items()
        }
        clean_facts(payload)
        async with self._uow() as uow:
            lock = await self._bump(uow, iid, lock_version)
            now = self._clock.now()
            if payload:
                await uow.catalog_proposals.apply_facts(iid, payload, ctx.user_id, now)
            for key, fact in facts.items():
                if fact.get("verified") is False:
                    await uow.catalog_card.set_verified(iid, key, None)
            for key in remove:
                await uow.catalog_card.delete_fact(iid, key)
            self._audit(
                uow, ctx, "catalog.facts_edited", iid, set=sorted(facts), removed=remove
            )
            await uow.commit()
        return lock

    async def save_description(
        self,
        ctx: AdmissionContext,
        iid: UUID,
        description: dict[str, Any],
        *,
        lock_version: int,
    ) -> int:
        """Replace the per-locale description."""
        self._require(ctx)
        cleaned = clean_description(description)
        async with self._uow() as uow:
            lock = await self._bump(uow, iid, lock_version)
            await uow.catalog_card.set_description(iid, cleaned, self._clock.now())
            self._audit(uow, ctx, "catalog.description_edited", iid)
            await uow.commit()
        return lock

    async def create_scholarship(
        self,
        ctx: AdmissionContext,
        iid: UUID,
        raw: Mapping[str, Any],
        *,
        lock_version: int,
    ) -> UUID:
        """Add a published scholarship to the institution."""
        self._require(ctx)
        values = _scholarship_values(raw, create=True)
        async with self._uow() as uow:
            await self._bump(uow, iid, lock_version)
            sid = await uow.catalog_card.create_scholarship(iid, values)
            self._audit(
                uow, ctx, "catalog.scholarship_created", iid, scholarship=str(sid)
            )
            await uow.commit()
        return sid

    async def update_scholarship(
        self,
        ctx: AdmissionContext,
        iid: UUID,
        sid: UUID,
        raw: Mapping[str, Any],
        *,
        lock_version: int,
    ) -> None:
        """Overwrite the given scholarship fields."""
        self._require(ctx)
        values = _scholarship_values(raw, create=False)
        if not values:
            raise ValidationFailedError(params={"field": "fields"})
        async with self._uow() as uow:
            await self._bump(uow, iid, lock_version)
            if not await uow.catalog_card.update_scholarship(iid, sid, values):
                raise AdmissionNotFoundError()
            self._audit(
                uow, ctx, "catalog.scholarship_edited", iid, scholarship=str(sid)
            )
            await uow.commit()

    async def delete_scholarship(
        self, ctx: AdmissionContext, iid: UUID, sid: UUID, *, lock_version: int
    ) -> None:
        """Remove a scholarship."""
        self._require(ctx)
        async with self._uow() as uow:
            await self._bump(uow, iid, lock_version)
            if not await uow.catalog_card.delete_scholarship(iid, sid):
                raise AdmissionNotFoundError()
            self._audit(
                uow, ctx, "catalog.scholarship_deleted", iid, scholarship=str(sid)
            )
            await uow.commit()
