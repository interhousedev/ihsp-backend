"""SQL repository of proofs, help requests and guest links."""
"""SQL repository of the proofs of items."""

import re
from datetime import datetime
from typing import cast
from uuid import UUID

from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.domain.help_proofs import (
    GuestLinkRecord,
    HelperActivity,
    HelperDirectoryEntry,
    HelpResponse,
    MetricView,
    Proof,
    ProofKind,
    ProofStatus,
)
from app.modules.admission.domain.workflow import (
    GuestLink,
    GuestScope,
    HelpKind,
    HelpRequest,
    HelpStatus,
)
from app.modules.admission.infrastructure.orm.help import (
    GuestLinkRow,
    GuestSessionRow,
    HelpRequestRow,
    HelpResponseRow,
)
from app.modules.admission.infrastructure.orm.profile import (
    ItemMetricRow,
    ItemRow,
    ProfileRow,
    ProofRow,
)
from app.modules.admission.domain.help_proofs import Proof, ProofKind, ProofStatus
from app.modules.admission.infrastructure.orm.profile import ItemRow, ProofRow
from app.shared.ids import new_id

from sqlalchemy import func, select, update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_FINISHED = ("closed", "cancelled", "expired", "declined")


def _proof(row: ProofRow) -> Proof:
    return Proof(
        id=row.id,
        item_id=row.item_id,
        kind=cast(ProofKind, row.kind),
        status=cast(ProofStatus, row.status),
        url=row.url,
        file_id=row.file_id,
        text_sha256=row.text_sha256,
        extraction=row.extraction,
        fetched_at=row.fetched_at,
        next_check_at=row.next_check_at,
        lock_version=row.lock_version,
    )


def _request(row: HelpRequestRow) -> HelpRequest:
    return HelpRequest(
        id=row.id,
        student_id=row.student_id,
        kind=cast(HelpKind, row.kind),
        brief=row.brief,
        expires_at=row.expires_at,
        item_id=row.item_id,
        helper_user_id=row.helper_user_id,
        status=cast(HelpStatus, row.status),
        lock_version=row.lock_version,
    )


def _link(row: GuestLinkRow) -> GuestLinkRecord:
    return GuestLinkRecord(
        link=GuestLink(
            id=row.id,
            student_id=row.student_id,
            help_request_id=row.help_request_id,
            scope=cast(tuple[GuestScope, ...], tuple(row.scope)),
            token_hash=row.token_hash,
            token_prefix=row.token_prefix,
            expires_at=row.expires_at,
            max_sessions=row.max_sessions,
            sessions_used=row.sessions_used,
            revoked_at=row.revoked_at,
        ),
        label=row.label,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_reason=row.revoked_reason,
        rotated_from=row.rotated_from,
        claimed_by=row.claimed_by,
    )


def _response(row: HelpResponseRow) -> HelpResponse:
    return HelpResponse(
        id=row.id,
        help_request_id=row.help_request_id,
        text=row.text,
        created_at=row.created_at,
        author_user_id=row.author_user_id,
        guest_link_id=row.guest_link_id,
        url=row.url,
        file_id=row.file_id,
    )


def _like(query: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", query.strip()) + "%"


class SqlHelpProofsRepository:
    """Proofs, help requests and guest links on one session."""
    """Proofs on one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self.session = session

    # proofs

    async def item_owner(self, item_id: UUID) -> UUID | None:
        """Return the student owning the item, or None."""
        owner: UUID | None = await self.session.scalar(
            select(ItemRow.student_id).where(ItemRow.id == item_id)
        )
        return owner

    async def add_proof(
        self,
        item_id: UUID,
        kind: ProofKind,
        *,
        url: str | None,
        file_id: UUID | None,
        text_sha256: str | None,
    ) -> Proof:
        """Insert a pending proof."""
        row = ProofRow(
            id=new_id(),
            item_id=item_id,
            kind=kind,
            url=url,
            file_id=file_id,
            text_sha256=text_sha256,
            status="pending",
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return _proof(row)

    async def get_proof(self, proof_id: UUID) -> Proof | None:
        """Return one proof."""
        row = await self.session.get(ProofRow, proof_id)
        return _proof(row) if row else None

    async def list_proofs(self, item_id: UUID) -> list[Proof]:
        """Return the item's proofs, oldest first."""
        rows = await self.session.scalars(
            select(ProofRow).where(ProofRow.item_id == item_id).order_by(ProofRow.id)
        )
        return [_proof(r) for r in rows]

    async def set_proof_result(
        self,
        proof_id: UUID,
        *,
        status: ProofStatus,
        fetched_at: datetime,
        text_sha256: str | None,
        extraction: str | None,
    ) -> Proof:
        """Record a verification result."""
        row = await self.session.get(ProofRow, proof_id)
        if row is None:
            raise AdmissionConflictError()
        row.status = status
        row.fetched_at = fetched_at
        row.text_sha256 = text_sha256 or row.text_sha256
        row.extraction = extraction
        row.lock_version += 1
        await self.session.flush()
        return _proof(row)

    # help requests

    async def add_request(self, request: HelpRequest) -> HelpRequest:
        """Insert a request."""
        row = HelpRequestRow(
            id=request.id,
            student_id=request.student_id,
            item_id=request.item_id,
            kind=request.kind,
            brief=request.brief,
            status=request.status,
            helper_user_id=request.helper_user_id,
            expires_at=request.expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return _request(row)

    async def get_request(self, request_id: UUID) -> HelpRequest | None:
        """Return one request."""
        row = await self.session.get(HelpRequestRow, request_id)
        return _request(row) if row else None

    async def save_request(self, request: HelpRequest) -> HelpRequest:
        """Write status and helper; raises AdmissionConflictError on a stale version."""
        result = await self.session.execute(
            update(HelpRequestRow)
            .where(
                HelpRequestRow.id == request.id,
                HelpRequestRow.lock_version == request.lock_version,
            )
            .values(
                status=request.status,
                helper_user_id=request.helper_user_id,
                updated_at=func.now(),
                lock_version=HelpRequestRow.lock_version + 1,
            )
            .returning(HelpRequestRow.id)
        )
        if result.first() is None:
            raise AdmissionConflictError()
        request.lock_version += 1
        return request

    async def list_requests(self, student_id: UUID) -> list[HelpRequest]:
        """Return the student's requests, newest first."""
        rows = await self.session.scalars(
            select(HelpRequestRow)
            .where(HelpRequestRow.student_id == student_id)
            .order_by(HelpRequestRow.id.desc())
        )
        return [_request(r) for r in rows]

    async def list_assigned(self, helper_id: UUID, now: datetime) -> list[HelpRequest]:
        """Return live requests assigned to the helper."""
        rows = await self.session.scalars(
            select(HelpRequestRow)
            .where(
                HelpRequestRow.helper_user_id == helper_id,
                HelpRequestRow.status.in_(("assigned", "accepted", "delivered")),
                HelpRequestRow.expires_at > now,
            )
            .order_by(HelpRequestRow.id.desc())
        )
        return [_request(r) for r in rows]

    async def count_open_requests(self, student_id: UUID) -> int:
        """Return the student's requests that are not finished."""
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(HelpRequestRow)
                .where(
                    HelpRequestRow.student_id == student_id,
                    HelpRequestRow.status.not_in(_FINISHED),
                )
            )
            or 0
        )

    async def add_response(
        self,
        request_id: UUID,
        *,
        author_user_id: UUID | None,
        guest_link_id: UUID | None,
        text: str,
        url: str | None,
        file_id: UUID | None,
        now: datetime,
    ) -> HelpResponse:
        """Insert a response."""
        row = HelpResponseRow(
            id=new_id(),
            help_request_id=request_id,
            author_user_id=author_user_id,
            guest_link_id=guest_link_id,
            text=text,
            url=url,
            file_id=file_id,
            created_at=now,
        )
        self.session.add(row)
        await self.session.flush()
        return _response(row)

    async def list_responses(self, request_id: UUID) -> list[HelpResponse]:
        """Return the request's responses, oldest first."""
        rows = await self.session.scalars(
            select(HelpResponseRow)
            .where(HelpResponseRow.help_request_id == request_id)
            .order_by(HelpResponseRow.id)
        )
        return [_response(r) for r in rows]

    async def search_helpers(
        self, query: str, *, exclude: UUID, limit: int
    ) -> list[HelperDirectoryEntry]:
        """Return opted-in helpers whose display name contains the query."""
        rows = await self.session.execute(
            select(ProfileRow.student_id, ProfileRow.helper_display_name)
            .where(
                ProfileRow.helper_opt_in.is_(True),
                ProfileRow.student_id != exclude,
                ProfileRow.helper_display_name.is_not(None),
                ProfileRow.helper_display_name.ilike(_like(query), escape="\\"),
            )
            .order_by(ProfileRow.helper_display_name)
            .limit(limit)
        )
        return [HelperDirectoryEntry(u, n) for u, n in rows if n]

    async def helper_opted_in(self, user_id: UUID) -> bool:
        """Return whether the user accepts help requests."""
        return bool(
            await self.session.scalar(
                select(ProfileRow.helper_opt_in).where(ProfileRow.student_id == user_id)
            )
        )

    async def activities_for_helper(
        self, student_id: UUID, *, item_id: UUID | None = None
    ) -> list[HelperActivity]:
        """Return the reduced activity list (current metrics only)."""
        stmt = select(ItemRow).where(ItemRow.student_id == student_id)
        if item_id is not None:
            stmt = stmt.where(ItemRow.id == item_id)
        items = list(await self.session.scalars(stmt.order_by(ItemRow.sort_order)))
        if not items:
            return []
        metrics = await self.session.scalars(
            select(ItemMetricRow)
            .where(
                ItemMetricRow.item_id.in_([i.id for i in items]),
                ItemMetricRow.horizon == "current",
            )
            .order_by(ItemMetricRow.id)
        )
        by_item: dict[UUID, list[MetricView]] = {}
        for m in metrics:
            by_item.setdefault(m.item_id, []).append(
                MetricView(m.label, format(m.value, "f"), m.unit)
            )
        return [
            HelperActivity(
                position=i.position,
                org=i.org,
                description=i.description,
                kind=i.kind,
                current_metrics=tuple(by_item.get(i.id, ())),
            )
            for i in items
        ]

    # guest links

    async def add_link(
        self,
        *,
        student_id: UUID,
        help_request_id: UUID,
        scope: tuple[GuestScope, ...],
        token_hash: str,
        token_prefix: str,
        label: str | None,
        expires_at: datetime,
        max_sessions: int,
        rotated_from: UUID | None,
        now: datetime,
    ) -> GuestLinkRecord:
        """Insert a link."""
        row = GuestLinkRow(
            id=new_id(),
            student_id=student_id,
            help_request_id=help_request_id,
            scope=list(scope),
            token_hash=token_hash,
            token_prefix=token_prefix,
            label=label,
            expires_at=expires_at,
            max_sessions=max_sessions,
            rotated_from=rotated_from,
            created_at=now,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return _link(row)

    async def get_link(self, link_id: UUID) -> GuestLinkRecord | None:
        """Return one link."""
        row = await self.session.get(GuestLinkRow, link_id)
        return _link(row) if row else None

    async def list_links(self, student_id: UUID) -> list[GuestLinkRecord]:
        """Return the student's links, newest first."""
        rows = await self.session.scalars(
            select(GuestLinkRow)
            .where(GuestLinkRow.student_id == student_id)
            .order_by(GuestLinkRow.id.desc())
        )
        return [_link(r) for r in rows]

    async def count_active(self, student_id: UUID, now: datetime) -> int:
        """Return the student's links that are neither revoked nor expired."""
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(GuestLinkRow)
                .where(
                    GuestLinkRow.student_id == student_id,
                    GuestLinkRow.revoked_at.is_(None),
                    GuestLinkRow.expires_at > now,
                )
            )
            or 0
        )

    async def by_hash(self, token_hash: str) -> GuestLinkRecord | None:
        """Return the link with this token hash."""
        row = await self.session.scalar(
            select(GuestLinkRow).where(GuestLinkRow.token_hash == token_hash)
        )
        return _link(row) if row else None

    async def revoke(self, link_id: UUID, now: datetime, reason: str) -> None:
        """Revoke a link (a repeat keeps the first reason)."""
        await self.session.execute(
            update(GuestLinkRow)
            .where(GuestLinkRow.id == link_id, GuestLinkRow.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def claim(self, link_id: UUID, user_id: UUID, now: datetime) -> None:
        """Record who claimed the link."""
        await self.session.execute(
            update(GuestLinkRow)
            .where(GuestLinkRow.id == link_id)
            .values(claimed_by=user_id, claimed_at=now)
        )

    async def redeem(
        self,
        token_hash: str,
        now: datetime,
        *,
        session_hash: str,
        ip_hash: str | None,
        session_expires_at: datetime,
    ) -> GuestLinkRecord | None:
        """Count one session atomically and store it; None when not usable."""
        row = await self.session.scalar(
            update(GuestLinkRow)
            .where(
                GuestLinkRow.token_hash == token_hash,
                GuestLinkRow.sessions_used < GuestLinkRow.max_sessions,
                GuestLinkRow.revoked_at.is_(None),
                GuestLinkRow.expires_at > now,
            )
            .values(sessions_used=GuestLinkRow.sessions_used + 1, last_used_at=now)
            .returning(GuestLinkRow)
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        self.session.add(
            GuestSessionRow(
                id=new_id(),
                guest_link_id=row.id,
                session_hash=session_hash,
                ip_hash=ip_hash,
                expires_at=session_expires_at,
                created_at=now,
            )
        )
        await self.session.flush()
        return _link(row)

    async def link_of_session(
        self, session_hash: str, now: datetime
    ) -> GuestLinkRecord | None:
        """Return the link of a live session whose link is still usable."""
        row = await self.session.scalar(
            select(GuestLinkRow)
            .join(GuestSessionRow, GuestSessionRow.guest_link_id == GuestLinkRow.id)
            .where(
                GuestSessionRow.session_hash == session_hash,
                GuestSessionRow.expires_at > now,
                GuestLinkRow.revoked_at.is_(None),
                GuestLinkRow.expires_at > now,
            )
        )
        return _link(row) if row else None
