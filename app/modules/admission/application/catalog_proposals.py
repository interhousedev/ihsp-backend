"""Catalog proposals: staff propose, an administrator or curator reviews."""

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.supp_prompts import (
    apply_proposed,
    clean_proposed,
)
from app.modules.admission.domain.catalog_display import LOGO_FITS, valid_logo_zoom
from app.modules.admission.domain.catalog_proposals import (
    FIELDS,
    MEDIA_FIELDS,
    CatalogProposal,
    ProposalKind,
    invalid_field,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CatalogDuplicateError,
    CatalogFactInvalidError,
    CatalogProposalLimitError,
    InvalidMediaUrlError,
    InvalidProofUrlError,
    InvalidTransitionError,
)
from app.modules.admission.domain.intl_facts import (
    clean_facts,
    clean_name,
    fold_name,
    has_userinfo,
)
from app.modules.admission.domain.permissions import KIND_ROLE, Permission
from app.modules.admission.domain.urls import is_https_url
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError, ValidationFailedError
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

_DAY = 86_400
DEFAULT_PER_DAY = 100
_ASPECT_MAX = 1000


def _fold_text_fields(payload: dict[str, Any]) -> None:
    """Store the name and the aliases NFC, single-spaced and stripped, case kept."""
    name = payload.get("name")
    if isinstance(name, str):
        if clean_name(name):
            payload["name"] = clean_name(name)
        else:
            del payload["name"]
    aliases = payload.get("aliases")
    if isinstance(aliases, list):
        kept = dict.fromkeys(
            clean_name(a) for a in aliases if isinstance(a, str) and clean_name(a)
        )
        if kept:
            payload["aliases"] = list(kept)
        else:
            del payload["aliases"]


def _clean_payload(
    kind: ProposalKind,
    fields: dict[str, Any],
    source_url: str,
    *,
    allow_empty: bool = False,
) -> dict[str, Any]:
    """Return the known, non-empty fields; raise when any is invalid."""
    if has_userinfo(source_url):
        raise InvalidProofUrlError()
    parts = urlsplit(source_url)
    if parts.scheme != "https" or not parts.hostname:
        raise InvalidProofUrlError()
    payload = {
        k: v for k, v in fields.items() if k in FIELDS[kind] and v not in (None, "", [])
    }
    bad = invalid_field(kind, payload)
    if bad is not None:
        raise ValidationFailedError(params={"field": bad})
    _fold_text_fields(payload)
    if not payload and not allow_empty:
        raise ValidationFailedError(params={"field": "fields"})
    _check_media_fields(payload)
    if "country" in payload:
        payload["country"] = payload["country"].upper()
    return payload


def _check_media_fields(payload: dict[str, Any]) -> None:
    """Raise when a logo or media field of the payload is invalid."""
    for key in MEDIA_FIELDS:
        if key in payload and not is_https_url(payload[key]):
            raise InvalidMediaUrlError(params={"field": key})
    if "logo_zoom" in payload and not valid_logo_zoom(payload["logo_zoom"]):
        raise ValidationFailedError(params={"field": "logo_zoom"})
    if "logo_fit" in payload and payload["logo_fit"] not in LOGO_FITS:
        raise ValidationFailedError(params={"field": "logo_fit"})
    aspect = payload.get("logo_aspect")
    if "logo_aspect" in payload and not (
        isinstance(aspect, (int, float))
        and not isinstance(aspect, bool)
        and 0 < aspect < _ASPECT_MAX
    ):
        raise ValidationFailedError(params={"field": "logo_aspect"})


class CatalogProposalService:
    """Propose, list and review catalog edits."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        limiter: RateLimiter | None = None,
        per_day: int = DEFAULT_PER_DAY,
    ) -> None:
        """Keep the transaction factory, the clock and the daily proposal limit."""
        self._uow = uow_factory
        self._clock = clock
        self._limiter = limiter
        self._per_day = per_day

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

    def require_proposer(self, ctx: AdmissionContext) -> None:
        """Raise `AdmissionForbiddenError` unless the caller may propose."""
        if not self._may_propose(ctx):
            raise AdmissionForbiddenError(params={"permission": "catalog:propose"})

    async def propose(
        self,
        ctx: AdmissionContext,
        *,
        kind: ProposalKind,
        target_id: UUID | None,
        fields: dict[str, Any],
        source_url: str,
        note: str | None,
        facts: Mapping[str, Mapping[str, Any]] | None = None,
        supp_prompts: Sequence[Mapping[str, Any]] | None = None,
    ) -> CatalogProposal:
        """Store a pending proposal; a new row needs its required fields.

        `facts` (institutions only) are the sourced international facts;
        `supp_prompts` (institutions only) are supplement prompts per cycle. A
        proposal may carry only facts or prompts when it edits an institution.
        """
        if not self._may_propose(ctx):
            raise AdmissionForbiddenError(params={"permission": "catalog:propose"})
        if facts and kind != "institution":
            raise CatalogFactInvalidError(
                params={"fact": next(iter(facts)), "reason": "kind"}
            )
        if supp_prompts and kind != "institution":
            raise ValidationFailedError(params={"field": "supp_prompts"})
        cleaned = clean_facts(facts or {})
        prompts = clean_proposed(supp_prompts or [])
        payload = _clean_payload(
            kind, fields, source_url, allow_empty=bool(cleaned or prompts)
        )
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
            supp_prompts=prompts,
            facts={
                k: {
                    "value": f.value,
                    "source_url": f.source_url,
                    "year": f.year,
                    "note": f.note,
                }
                for k, f in cleaned.items()
            },
        )
        missing = proposal.missing_on_create()
        if missing:
            raise ValidationFailedError(params={"field": missing[0]})
        async with self._uow() as uow:
            repo = uow.catalog_proposals
            if target_id is not None and not await repo.target_exists(kind, target_id):
                raise AdmissionNotFoundError()
            if kind == "scholarship":
                await self._check_scholarship_institution(repo, payload)
            if kind == "institution" and target_id is None:
                await self._reject_duplicate(repo, payload)
            await self._hit(ctx)
            saved = await repo.add(proposal)
            uow.access.audit(
                AuditEvent(
                    action="catalog.proposal_created",
                    actor_id=ctx.user_id,
                    student_id=None,
                    object_type=f"catalog_{kind}",
                    object_id=saved.id,
                    meta={"target_id": str(target_id) if target_id else None},
                )
            )
            await uow.commit()
        return saved

    @staticmethod
    async def _reject_duplicate(repo: Any, payload: Mapping[str, Any]) -> None:
        """Lock submissions and raise when the institution already exists."""
        await repo.lock_submissions()
        aliases = payload.get("aliases")
        aliases = aliases if isinstance(aliases, list) else []
        raw = [payload["name"], *aliases]
        names = [fold_name(n) for n in raw if isinstance(n, str) and n.strip()]
        domain = payload.get("website_domain")
        found = await repo.find_duplicate(
            names, fold_name(domain) if isinstance(domain, str) else None
        )
        if found is not None:
            which, found_id = found
            raise CatalogDuplicateError(params={f"{which}_id": str(found_id)})

    @staticmethod
    async def _check_scholarship_institution(
        repo: Any, payload: Mapping[str, Any]
    ) -> None:
        """Raise when the scholarship names an institution that does not exist."""
        raw = payload.get("institution_id")
        if raw is not None and not await repo.target_exists("institution", UUID(raw)):
            raise ValidationFailedError(params={"field": "institution_id"})

    async def _hit(self, ctx: AdmissionContext) -> None:
        if self._limiter is None:
            return
        try:
            await self._limiter.hit(
                f"admission:catalog_propose:{ctx.user_id}",
                limit=self._per_day,
                window_seconds=_DAY,
            )
        except RateLimitedError as e:
            raise CatalogProposalLimitError(
                params={**(e.params or {}), "limit": self._per_day}
            ) from e

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
            now = self._clock.now()
            applied = (
                await uow.catalog_proposals.apply(
                    current, reviewer_id=ctx.user_id, now=now
                )
                if approve
                else None
            )
            if applied is not None and current.supp_prompts:
                await apply_proposed(uow, applied, current.supp_prompts)
            reviewed = dataclasses.replace(
                current,
                status="approved" if approve else "rejected",
                reviewed_by=ctx.user_id,
                reviewed_at=now,
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
