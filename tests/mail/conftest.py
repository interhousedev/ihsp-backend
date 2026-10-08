"""Fixtures of the mail tests."""

from app.shared.contracts.identity import UserRef
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.mail.world import MailWorld, build_world

import pytest
from redis.asyncio import Redis


@pytest.fixture
def world(clock: FixedClock, kicker: FakeTaskKicker, redis: Redis) -> MailWorld:
    """The mail module over in-memory adapters (clock 2026-10-06 09:00 UTC)."""
    return build_world(clock, kicker, redis)


@pytest.fixture
def student(world: MailWorld) -> UserRef:
    """Aleksey Brastilov, active student with the mailbox aleksey.brastilov@..."""
    return world.student()
