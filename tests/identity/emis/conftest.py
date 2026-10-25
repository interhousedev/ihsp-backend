"""Fixtures of the B2 tests."""

from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.identity.emis.world import World, build_world

import pytest
from fakeredis.aioredis import FakeRedis


@pytest.fixture
def world(redis: FakeRedis, clock: FixedClock, kicker: FakeTaskKicker) -> World:
    """The use cases of task B2 over in-memory fakes."""
    return build_world(redis, clock, kicker)
