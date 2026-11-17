"""In-memory proofs and the service wiring of the proof unit tests."""

import dataclasses
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.application.proofs import ProofService
from app.modules.admission.domain.help_proofs import Proof, ProofKind, ProofStatus
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import (
    NOW,
    FakeConsents,
    FakeMembership,
    FakeStore,
    FakeUow,
    student_ref,
)
from tests.fakes.clock import FixedClock

STUDENT = new_id()
OTHER = new_id()


async def _ten(user_id: object) -> int | None:
    return 10


class ProofState:
    """Item owners and proof rows."""

    def __init__(self) -> None:
        """Start empty."""
        self.items: dict[UUID, UUID] = {}
        self.proofs: dict[UUID, Proof] = {}


class FakeProofs:
    """Implements the ProofRepository protocol over ProofState."""

    def __init__(self, h: ProofState) -> None:
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


class ProofUow(FakeUow):
    """FakeUow with the proof repository (`help_proofs`)."""

    def __init__(self, s: FakeStore, h: ProofState) -> None:
        """Bind both states."""
        super().__init__(s)
        self.help_proofs = FakeProofs(h)


class NoLimit:
    """A rate limiter that never limits."""

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        return 1


class ProofKit:
    """The proof service over one store."""

    def __init__(self, fetcher: Any = None) -> None:
        """Wire everything."""
        self.store = FakeStore()
        self.h = ProofState()
        self.clock = FixedClock(NOW)
        membership = FakeMembership(
            [student_ref(STUDENT, new_id()), student_ref(OTHER, new_id())]
        )
        uow = lambda: ProofUow(self.store, self.h)  # noqa: E731
        access = AccessPolicy(uow, membership, FakeConsents({}), self.clock, {10, 11})
        self.resolver = ResolveAdmissionActor(uow, membership, self.clock, {10, 11})
        self.proofs = ProofService(
            uow,  # type: ignore[arg-type]
            access,
            self.clock,
            NoLimit(),
            _ten,
            None,
            fetcher,
        )
        self.item = new_id()
        self.h.items[self.item] = STUDENT

    async def ctx(self, user: UUID = STUDENT) -> AdmissionContext:
        """Return the context of a student."""
        return await self.resolver.execute(Actor(user, frozenset({Role.STUDENT})))
