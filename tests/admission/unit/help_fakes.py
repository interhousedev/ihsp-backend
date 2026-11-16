"""In-memory proofs, help requests and guest links for the unit tests."""

import dataclasses
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.domain.help_proofs import (
    GuestLinkRecord,
    HelperActivity,
    HelperDirectoryEntry,
    HelpResponse,
    Proof,
    ProofKind,
    ProofStatus,
)
from app.modules.admission.domain.workflow import GuestLink, GuestScope, HelpRequest
from app.shared.ids import new_id
from tests.admission.unit.fakes import FakeStore, FakeUow


class HelpState:
    """Rows of the proofs, help and guest tables."""

    def __init__(self) -> None:
        """Start empty."""
        self.items: dict[UUID, UUID] = {}
        self.proofs: dict[UUID, Proof] = {}
        self.requests: dict[UUID, HelpRequest] = {}
        self.responses: list[HelpResponse] = []
        self.links: dict[UUID, GuestLinkRecord] = {}
        self.sessions: dict[str, tuple[UUID, datetime]] = {}
        self.directory: dict[UUID, str] = {}
        self.activities: list[HelperActivity] = []
        self.activity_item_ids: list[UUID | None] = []
        self.notifications: list[Any] = []


class FakeHelpProofs:
    """Implements the HelpProofsRepository protocol over HelpState."""

    def __init__(self, h: HelpState) -> None:
        """Bind the state."""
        self.h = h

    async def item_owner(self, item_id: UUID) -> UUID | None:
        return self.h.items.get(item_id)

    async def add_proof(
        self,
        item_id: UUID,
        kind: ProofKind,
        *,
        url: str | None,
        file_id: UUID | None,
        text_sha256: str | None,
    ) -> Proof:
        p = Proof(new_id(), item_id, kind, "pending", url=url, file_id=file_id)
        self.h.proofs[p.id] = p
        return p

    async def get_proof(self, proof_id: UUID) -> Proof | None:
        return self.h.proofs.get(proof_id)

    async def list_proofs(self, item_id: UUID) -> list[Proof]:
        return [p for p in self.h.proofs.values() if p.item_id == item_id]

    async def set_proof_result(
        self,
        proof_id: UUID,
        *,
        status: ProofStatus,
        fetched_at: datetime,
        text_sha256: str | None,
        extraction: str | None,
    ) -> Proof:
        p = dataclasses.replace(
            self.h.proofs[proof_id],
            status=status,
            fetched_at=fetched_at,
            extraction=extraction,
        )
        self.h.proofs[proof_id] = p
        return p

    async def add_request(self, request: HelpRequest) -> HelpRequest:
        self.h.requests[request.id] = request
        return request

    async def get_request(self, request_id: UUID) -> HelpRequest | None:
        r = self.h.requests.get(request_id)
        return dataclasses.replace(r) if r else None

    async def save_request(self, request: HelpRequest) -> HelpRequest:
        request.lock_version += 1
        self.h.requests[request.id] = dataclasses.replace(request)
        return request

    async def list_requests(self, student_id: UUID) -> list[HelpRequest]:
        return [r for r in self.h.requests.values() if r.student_id == student_id]

    async def list_assigned(self, helper_id: UUID, now: datetime) -> list[HelpRequest]:
        return [
            r
            for r in self.h.requests.values()
            if r.helper_user_id == helper_id and r.expires_at > now
        ]

    async def count_open_requests(self, student_id: UUID) -> int:
        live = ("open", "assigned", "accepted")
        return sum(
            r.student_id == student_id and r.status in live
            for r in self.h.requests.values()
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
        r = HelpResponse(
            new_id(),
            request_id,
            text,
            now,
            author_user_id=author_user_id,
            guest_link_id=guest_link_id,
            url=url,
            file_id=file_id,
        )
        self.h.responses.append(r)
        return r

    async def list_responses(self, request_id: UUID) -> list[HelpResponse]:
        return [r for r in self.h.responses if r.help_request_id == request_id]

    async def search_helpers(
        self, query: str, *, exclude: UUID, limit: int
    ) -> list[HelperDirectoryEntry]:
        return [
            HelperDirectoryEntry(u, n)
            for u, n in self.h.directory.items()
            if u != exclude and query.lower() in n.lower()
        ][:limit]

    async def helper_opted_in(self, user_id: UUID) -> bool:
        return user_id in self.h.directory

    async def activities_for_helper(
        self, student_id: UUID, *, item_id: UUID | None = None
    ) -> list[HelperActivity]:
        self.h.activity_item_ids.append(item_id)
        return list(self.h.activities)

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
        link = GuestLink(
            new_id(),
            student_id,
            help_request_id,
            scope,
            token_hash,
            token_prefix,
            expires_at,
            max_sessions,
        )
        rec = GuestLinkRecord(link, label, now, rotated_from=rotated_from)
        self.h.links[link.id] = rec
        return rec

    async def get_link(self, link_id: UUID) -> GuestLinkRecord | None:
        return self.h.links.get(link_id)

    async def list_links(self, student_id: UUID) -> list[GuestLinkRecord]:
        return [r for r in self.h.links.values() if r.link.student_id == student_id]

    async def count_active(self, student_id: UUID, now: datetime) -> int:
        return sum(
            r.link.student_id == student_id
            and r.link.revoked_at is None
            and r.link.expires_at > now
            for r in self.h.links.values()
        )

    async def by_hash(self, token_hash: str) -> GuestLinkRecord | None:
        return next(
            (r for r in self.h.links.values() if r.link.token_hash == token_hash),
            None,
        )

    async def revoke(self, link_id: UUID, now: datetime, reason: str) -> None:
        rec = self.h.links[link_id]
        link = dataclasses.replace(rec.link, revoked_at=now)
        self.h.links[link_id] = dataclasses.replace(
            rec, link=link, revoked_reason=reason
        )

    async def claim(self, link_id: UUID, user_id: UUID, now: datetime) -> None:
        self.h.links[link_id] = dataclasses.replace(
            self.h.links[link_id], claimed_by=user_id
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
        rec = await self.by_hash(token_hash)
        if rec is None or not rec.link.usable(now):
            return None
        link = dataclasses.replace(rec.link, sessions_used=rec.link.sessions_used + 1)
        rec = dataclasses.replace(rec, link=link)
        self.h.sessions[session_hash] = (rec.link.id, session_expires_at)
        self.h.links[rec.link.id] = dataclasses.replace(rec, last_used_at=now)
        return self.h.links[rec.link.id]

    async def link_of_session(
        self, session_hash: str, now: datetime
    ) -> GuestLinkRecord | None:
        found = self.h.sessions.get(session_hash)
        if found is None or found[1] <= now:
            return None
        rec = self.h.links[found[0]]
        return (
            rec if rec.link.revoked_at is None and rec.link.expires_at > now else None
        )


class HelpUow(FakeUow):
    """FakeUow with the help repository and a notification sink."""

    def __init__(self, s: FakeStore, h: HelpState) -> None:
        """Bind both states."""
        super().__init__(s)
        self.help_proofs = FakeHelpProofs(h)
        self.notify = lambda *drafts: h.notifications.extend(drafts)


class NoLimit:
    """A rate limiter that never limits."""

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        return 1
