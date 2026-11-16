"""Shared wiring of the proofs, help and guest unit tests."""

import dataclasses
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.application.guest import GuestService
from app.modules.admission.application.help import HelpService
from app.modules.admission.application.proofs import ProofService
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import (
    NOW,
    FakeConsents,
    FakeMembership,
    FakeStore,
    student_ref,
)
from tests.admission.unit.help_fakes import HelpState, HelpUow, NoLimit
from tests.fakes.clock import FixedClock

STUDENT = new_id()
OTHER = new_id()
HELPER = new_id()


async def _ten(user_id: object) -> int | None:
    return 10


class HelpKit:
    """Services over one store."""

    def __init__(self, fetcher: Any = None, max_active: int = 2) -> None:
        """Wire everything."""
        self.store = FakeStore()
        self.h = HelpState()
        self.clock = FixedClock(NOW)
        membership = FakeMembership(
            [student_ref(STUDENT, new_id()), student_ref(OTHER, new_id())]
        )
        uow = lambda: HelpUow(self.store, self.h)  # noqa: E731
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
        self.help = HelpService(
            uow, access, self.clock, NoLimit()  # type: ignore[arg-type]
        )
        self.guest = GuestService(
            uow,
            access,
            self.clock,
            NoLimit(),  # type: ignore[arg-type]
            default_days=14,
            default_sessions=2,
            max_active=max_active,
        )
        self.item = new_id()
        self.h.items[self.item] = STUDENT

    async def ctx(self, user: UUID = STUDENT) -> AdmissionContext:
        """Return the context of a student."""
        return await self.resolver.execute(Actor(user, frozenset({Role.STUDENT})))

    async def helper_ctx(self) -> AdmissionContext:
        """Return a context whose user is the helper."""
        base = await self.ctx()
        return dataclasses.replace(base, actor=Actor(HELPER, frozenset({Role.STUDENT})))
