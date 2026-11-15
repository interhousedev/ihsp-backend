"""The consent gate remembers a pass for a short time and forgets it on publish."""

from typing import Any

from app.modules.legal.application.queries import RequireConsent
from app.modules.legal.domain.errors import LegalAcceptanceRequiredError
from app.modules.legal.ports.unit_of_work import UowFactory
from app.shared.contracts.legal import LegalItem
from tests.fakes.legal.uow import fake_uow_factory
from tests.legal.conftest import LegalHarness

import pytest


class Counting:
    """A unit-of-work factory that counts how often the gate opens one."""

    def __init__(self, inner: UowFactory) -> None:
        """Wrap the fake factory."""
        self.inner, self.calls = inner, 0

    def __call__(self) -> Any:
        """Open the inner unit of work."""
        self.calls += 1
        return self.inner()


async def _accept(legal: LegalHarness, kind: str, version: int) -> None:
    await legal.services.accept.execute(
        legal.student.user_id, [LegalItem(kind, version)], ip=None, user_agent=None
    )


async def test_a_pass_is_cached_until_the_ttl(legal: LegalHarness) -> None:
    """Within the TTL the gate does not read the store; after it, it reads again."""
    await legal.publish("privacy")
    await _accept(legal, "privacy", 1)
    now = [100.0]
    uows = Counting(fake_uow_factory(legal.store))
    gate = RequireConsent(uow_factory=uows, ttl_seconds=30, monotonic=lambda: now[0])
    uid = legal.student.user_id

    await gate.execute(uid)
    await gate.execute(uid)
    now[0] += 29
    await gate.execute(uid)
    assert uows.calls == 1

    now[0] += 2
    await gate.execute(uid)
    assert uows.calls == 2


async def test_a_refusal_is_not_cached(legal: LegalHarness) -> None:
    """Accepting takes effect on the very next request."""
    await legal.publish("privacy")
    gate = legal.services.require_consent
    uid = legal.student.user_id
    with pytest.raises(LegalAcceptanceRequiredError):
        await gate.execute(uid)

    await _accept(legal, "privacy", 1)

    await gate.execute(uid)


async def test_publishing_forgets_cached_passes(legal: LegalHarness) -> None:
    """A new version blocks a user whose pass was cached a moment ago."""
    await legal.publish("privacy")
    await _accept(legal, "privacy", 1)
    gate = legal.services.require_consent
    await gate.execute(legal.student.user_id)

    await legal.publish("privacy")

    with pytest.raises(LegalAcceptanceRequiredError):
        await gate.execute(legal.student.user_id)
