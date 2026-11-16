"""Port: storage of proofs, help requests and guest links."""

from datetime import datetime
from typing import Protocol
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
from app.modules.admission.domain.workflow import GuestScope, HelpRequest


class ProofRepository(Protocol):
    """Proofs of items."""

    async def item_owner(self, item_id: UUID) -> UUID | None:
        """Return the student owning the item, or None."""
        ...

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
        ...

    async def get_proof(self, proof_id: UUID) -> Proof | None:
        """Return one proof."""
        ...

    async def list_proofs(self, item_id: UUID) -> list[Proof]:
        """Return the item's proofs, oldest first."""
        ...

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
        ...


class HelpRepository(Protocol):
    """Help requests, responses and the helper directory."""

    async def add_request(self, request: HelpRequest) -> HelpRequest:
        """Insert a request."""
        ...

    async def get_request(self, request_id: UUID) -> HelpRequest | None:
        """Return one request."""
        ...

    async def save_request(self, request: HelpRequest) -> HelpRequest:
        """Write status and helper; raises AdmissionConflictError on a stale version."""
        ...

    async def list_requests(self, student_id: UUID) -> list[HelpRequest]:
        """Return the student's requests, newest first."""
        ...

    async def list_assigned(self, helper_id: UUID, now: datetime) -> list[HelpRequest]:
        """Return live requests assigned to the helper."""
        ...

    async def count_open_requests(self, student_id: UUID) -> int:
        """Return the student's requests that are not finished."""
        ...

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
        ...

    async def list_responses(self, request_id: UUID) -> list[HelpResponse]:
        """Return the request's responses, oldest first."""
        ...

    async def search_helpers(
        self, query: str, *, exclude: UUID, limit: int
    ) -> list[HelperDirectoryEntry]:
        """Return opted-in helpers whose display name contains the query."""
        ...

    async def helper_opted_in(self, user_id: UUID) -> bool:
        """Return whether the user accepts help requests."""
        ...

    async def activities_for_helper(self, student_id: UUID) -> list[HelperActivity]:
        """Return the reduced activity list (current metrics only)."""
        ...


class GuestLinkRepository(Protocol):
    """Guest links and their sessions."""

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
        ...

    async def get_link(self, link_id: UUID) -> GuestLinkRecord | None:
        """Return one link."""
        ...

    async def list_links(self, student_id: UUID) -> list[GuestLinkRecord]:
        """Return the student's links, newest first."""
        ...

    async def count_active(self, student_id: UUID, now: datetime) -> int:
        """Return the student's links that are neither revoked nor expired."""
        ...

    async def by_hash(self, token_hash: str) -> GuestLinkRecord | None:
        """Return the link with this token hash."""
        ...

    async def revoke(self, link_id: UUID, now: datetime, reason: str) -> None:
        """Revoke a link (a repeat keeps the first reason)."""
        ...

    async def claim(self, link_id: UUID, user_id: UUID, now: datetime) -> None:
        """Record who claimed the link."""
        ...

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
        ...

    async def link_of_session(
        self, session_hash: str, now: datetime
    ) -> GuestLinkRecord | None:
        """Return the link of a live session whose link is still usable."""
        ...


class HelpProofsRepository(
    ProofRepository, HelpRepository, GuestLinkRepository, Protocol
):
    """The three repositories, reached as `uow.help_proofs`."""


__all__ = [
    "GuestLinkRepository",
    "HelpProofsRepository",
    "HelpRepository",
    "ProofRepository",
]
