"""Fixtures of the B1 tests."""

from app.settings import Settings
from app.shared.i18n.core import I18nCore
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.identity.build_world import build_world
from tests.identity.support import World

import pytest
from fakeredis.aioredis import FakeRedis


@pytest.fixture
def auth_world(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
) -> World:
    """The B1 use cases over in-memory fakes (Hydra, senders, unit of work)."""
    return build_world(settings, i18n, redis, clock, kicker)
