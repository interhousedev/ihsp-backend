"""Proof links and files for an item (§10): reachability check through safe_fetch."""

from __future__ import annotations

import builtins
import hashlib
import html
import re
from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidProofUrlError,
    ProofSourceError,
)
from app.modules.admission.domain.help_proofs import (
    Proof,
    ProofKind,
    ProofStatus,
    detect_url_kind,
    validate_proof_url,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.ai import QuotaOf
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.rate_limit import RateLimiter
from app.shared.safe_fetch import FetchPolicy, SafeFetcher, any_public_host

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TITLE_MAX = 200
_DAY = 86400
_MIME = frozenset({"text/html", "text/plain", "application/json", "application/pdf"})


class _FetchFailed(Exception):
    """The page could not be fetched (transport, status, size, type)."""


def _unsafe(details: str) -> Exception:
    return InvalidProofUrlError(params={"reason": "unsafe"})


def _failed(details: str) -> Exception:
    return _FetchFailed(details)


def build_fetcher() -> SafeFetcher:
    """Return the fetcher for proof pages: https only, any public host."""
    policy = FetchPolicy(
        schemes=frozenset({"https"}),
        ports=frozenset({443}),
        allowed_hosts=any_public_host,
        redirect_policy="revalidate_any",
        mime_allow_list=_MIME,
        max_bytes=2 * 1024 * 1024,
        total_timeout=8.0,
        connect_timeout=3.0,
        accept="text/html,text/plain;q=0.9,application/json;q=0.5,*/*;q=0.1",
    )
    return SafeFetcher(policy, unsafe=_unsafe, failed=_failed)


@dataclass(frozen=True, slots=True)
class ProofResult:
    """Proof plus the page title seen during the check."""

    proof: Proof
    title: str | None = None


class ProofService:
    """Add and list proofs of an item; only the owner writes."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        clock: Clock,
        limiter: RateLimiter,
        per_day: QuotaOf,
        files: FilesApi | None = None,
        fetcher: SafeFetcher | None = None,
    ) -> None:
        """Keep the collaborators; `per_day` caps checks per student."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock
        self._limiter = limiter
        self._per_day = per_day
        self._files = files
        self._fetcher = fetcher or build_fetcher()

    async def _student(self, ctx: AdmissionContext, item_id: UUID) -> UUID:
        async with self._uow() as uow:
            owner = await uow.help_proofs.item_owner(item_id)
        if owner is None:
            raise AdmissionNotFoundError()
        return owner

    async def list(self, ctx: AdmissionContext, item_id: UUID) -> builtins.list[Proof]:
        """Return the item's proofs (owner or staff in scope)."""
        student = await self._student(ctx, item_id)
        await self._access.require(
            ctx, student, Permission.ACTIVITIES_READ, object_type="proof"
        )
        async with self._uow() as uow:
            return await uow.help_proofs.list_proofs(item_id)

    async def add(
        self,
        ctx: AdmissionContext,
        item_id: UUID,
        *,
        url: str | None = None,
        file_id: UUID | None = None,
        pasted_text: str | None = None,
    ) -> ProofResult:
        """Store a proof and check it; exactly one of url, file_id, pasted_text."""
        if sum(v is not None for v in (url, file_id, pasted_text)) != 1:
            raise ProofSourceError()
        student = await self._student(ctx, item_id)
        resolution = await self._access.require(
            ctx, student, Permission.ACTIVITIES_READ, object_type="proof"
        )
        if not resolution.owner:
            raise AdmissionForbiddenError(params={"permission": "proofs:edit"})
        if url is not None:
            return await self._add_url(ctx, item_id, validate_proof_url(url))
        if file_id is not None:
            return await self._add_file(ctx, item_id, file_id)
        assert pasted_text is not None
        digest = hashlib.sha256(pasted_text.encode()).hexdigest()
        return await self._store(item_id, "self_provided", None, None, digest, True)

    async def _store(
        self,
        item_id: UUID,
        kind: ProofKind,
        url: str | None,
        file_id: UUID | None,
        digest: str | None,
        done: bool,
    ) -> ProofResult:
        async with self._uow() as uow:
            proof = await uow.help_proofs.add_proof(
                item_id, kind, url=url, file_id=file_id, text_sha256=digest
            )
            if done:
                proof = await uow.help_proofs.set_proof_result(
                    proof.id,
                    status="unverifiable",
                    fetched_at=self._clock.now(),
                    text_sha256=digest,
                    extraction=None,
                )
            await uow.commit()
        return ProofResult(proof)

    async def _add_file(
        self, ctx: AdmissionContext, item_id: UUID, file_id: UUID
    ) -> ProofResult:
        ref = await self._files.get(file_id) if self._files else None
        if ref is None or ref.owner_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return await self._store(item_id, "file", None, file_id, None, True)

    async def _add_url(
        self, ctx: AdmissionContext, item_id: UUID, url: str
    ) -> ProofResult:
        limit = await self._per_day(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:proof:{ctx.user_id}", limit=limit, window_seconds=_DAY
            )
        kind = detect_url_kind(url)
        pending = await self._store(item_id, kind, url, None, None, False)
        status: ProofStatus
        digest: str | None = None
        title: str | None = None
        extraction: str | None = None
        try:
            body = await self._fetcher.fetch(url)
        except _FetchFailed:
            status = "unverifiable" if kind == "linkedin" else "failed"
        else:
            status = "unverifiable" if kind == "linkedin" else "checked"
            digest = hashlib.sha256(body.data).hexdigest()
            title = _title(body.data) if body.content_type == "text/html" else None
            extraction = "title" if title else "none"
        async with self._uow() as uow:
            proof = await uow.help_proofs.set_proof_result(
                pending.proof.id,
                status=status,
                fetched_at=self._clock.now(),
                text_sha256=digest,
                extraction=extraction,
            )
            await uow.commit()
        return ProofResult(proof, title)


def _title(data: bytes) -> str | None:
    match = _TITLE.search(data[:200_000].decode("utf-8", "replace"))
    if match is None:
        return None
    text = " ".join(html.unescape(match.group(1)).split())
    return text[:_TITLE_MAX] or None
