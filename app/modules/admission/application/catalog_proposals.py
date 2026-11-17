"""Catalog proposals: staff propose, an administrator or curator reviews."""

import dataclasses
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.catalog_display import LOGO_FITS, valid_logo_zoom
from app.modules.admission.domain.catalog_proposals import (
    FIELDS,
    MEDIA_FIELDS,
    CatalogProposal,
    ProposalKind,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidMediaUrlError,
    InvalidProofUrlError,
    InvalidTransitionError,
)
from app.modules.admission.domain.permissions import KIND_ROLE, Permission
from app.modules.admission.domain.urls import is_https_url
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.ids import new_id


def _clean_payload(
    kind: ProposalKind, fields: dict[str, Any], source_url: str
) -> dict[str, Any]:
    """Return the known, non-empty fields; raise when any is invalid."""
    parts = urlsplit(source_url)
    if parts.scheme != "https" or not parts.hostname:
        raise InvalidProofUrlError()
    payload = {
        k: v for k, v in fields.items() if k in FIELDS[kind] and v not in (None, "", [])
    }
    if not payload:
        raise ValidationFailedError(params={"field": "fields"})
    for key in MEDIA_FIELDS:
        if key in payload and not is_https_url(payload[key]):
            raise InvalidMediaUrlError(params={"field": key})
    if "logo_zoom" in payload and not valid_logo_zoom(payload["logo_zoom"]):
        raise ValidationFailedError(params={"field": "logo_zoom"})
    if "logo_fit" in payload and payload["logo_fit"] not in LOGO_FITS:
        raise ValidationFailedError(params={"field": "logo_fit"})
    aspect = payload.get("logo_aspect")
    if "logo_aspect" in payload and not (
        isinstance(aspect, (int, float)) and aspect > 0
    ):
        raise ValidationFailedError(params={"field": "logo_aspect"})
    return payload


class CatalogProposalService:
    """Propose, list and review catalog edits."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Keep the transaction factory and the clock."""
        self._uow = uow_factory
        self._clock = clock

    def can_review(self, ctx: AdmissionContext) -> bool:
        """Return whether the caller is an administrator or a live catalog curator."""
        if Role.ADMIN in ctx.actor.roles:
            return True
        now = self._clock.now()
        return any(
            a.active_at(now)
            and KIND_ROLE.get(a.role.kind) in ctx.actor.roles
            and Permission.CATALOG_CURATE in a.role.permissions
            for a in ctx.assignments
        )

    def _may_propose(self, ctx: AdmissionContext) -> bool:
        return (
            ctx.admission.is_staff
            or Role.ADMIN in ctx.actor.roles
            or self.can_review(ctx)
        )

    async def propose(
        self,
        ctx: AdmissionContext,
        *,
        kind: ProposalKind,
        target_id: UUID | None,
        fields: dict[str, Any],
        source_url: str,
        note: str | None,
    ) -> CatalogProposal:
        """Store a pending proposal; a new row needs its required fields."""
        if not self._may_propose(ctx):
            raise AdmissionForbiddenError(params={"permission": "catalog:propose"})
        payload = _clean_payload(kind, fields, source_url)
        proposal = CatalogProposal(
            id=new_id(),
            kind=kind,
            target_id=target_id,
            payload=payload,
            source_url=source_url,
            note=note,
            status="pending",
            proposed_by=ctx.user_id,
            created_at=self._clock.now(),
        )
        missing = proposal.missing_on_create()
        if missing:
            raise ValidationFailedError(params={"field": missing[0]})
        async with self._uow() as uow:
            if target_id is not None and not await uow.catalog_proposals.target_exists(
                kind, target_id
            ):
                raise AdmissionNotFoundError()
            saved = await uow.catalog_proposals.add(proposal)
            await uow.commit()
        return saved

    async def edit_logo(
        self,
        ctx: AdmissionContext,
        institution_id: UUID,
        *,
        zoom: float | None,
        fit: str | None,
    ) -> None:
        """Set the logo zoom or fit of an institution (admin or live curator)."""
        if not self.can_review(ctx):
            raise AdmissionForbiddenError(params={"permission": "catalog:curate"})
        if zoom is not None and not valid_logo_zoom(zoom):
            raise ValidationFailedError(params={"field": "logo_zoom"})
        if fit is not None and fit not in LOGO_FITS:
            raise ValidationFailedError(params={"field": "logo_fit"})
        if zoom is None and fit is None:
            raise ValidationFailedError(params={"field": "fields"})
        async with self._uow() as uow:
            if not await uow.catalog_proposals.set_logo(
                institution_id, zoom=zoom, fit=fit
            ):
                raise AdmissionNotFoundError()
            uow.access.audit(
                AuditEvent(
                    action="catalog.logo_edited",
                    actor_id=ctx.user_id,
                    student_id=None,
                    object_type="catalog_institution",
                    object_id=institution_id,
                    meta={"logo_zoom": zoom, "logo_fit": fit},
                )
            )
            await uow.commit()

    async def list(
        self, ctx: AdmissionContext, *, status: str | None
    ) -> list[CatalogProposal]:
        """Reviewers see every proposal; other staff see their own."""
        if not self._may_propose(ctx):
            raise AdmissionForbiddenError(params={"permission": "catalog:propose"})
        own = None if self.can_review(ctx) else ctx.user_id
        async with self._uow() as uow:
            return await uow.catalog_proposals.list(status=status, proposed_by=own)

    async def review(
        self,
        ctx: AdmissionContext,
        proposal_id: UUID,
        *,
        approve: bool,
        note: str | None,
        lock_version: int,
    ) -> CatalogProposal:
        """Approve (publishing the change) or reject a pending proposal."""
        if not self.can_review(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.CATALOG_CURATE.value}
            )
        async with self._uow() as uow:
            current = await uow.catalog_proposals.get(proposal_id)
            if current is None:
                raise AdmissionNotFoundError()
            if current.status != "pending":
                raise InvalidTransitionError(params={"status": current.status})
            applied = await uow.catalog_proposals.apply(current) if approve else None
            reviewed = dataclasses.replace(
                current,
                status="approved" if approve else "rejected",
                reviewed_by=ctx.user_id,
                reviewed_at=self._clock.now(),
                review_note=note,
                applied_id=applied,
            )
            saved = await uow.catalog_proposals.save_review(
                reviewed, expected_lock=lock_version
            )
            uow.access.audit(
                AuditEvent(
                    action=(
                        "catalog.proposal_approved"
                        if approve
                        else "catalog.proposal_rejected"
                    ),
                    actor_id=ctx.user_id,
                    student_id=None,
                    object_type=f"catalog_{current.kind}",
                    object_id=applied or current.id,
                    meta={"proposal_id": str(current.id)},
                )
            )
            await uow.commit()
        return saved
