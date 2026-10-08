"""Builds the B1 use cases over in-memory fakes."""

from typing import Any, cast

from app.modules.identity.infrastructure.argon2_hasher import Argon2PasswordHasher
from app.modules.identity.wiring_auth import build_auth
from app.settings import Settings
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.identity.hydra import FakeHydra
from tests.fakes.identity.senders import (
    FakeEmailSender,
    FakeOtpSender,
    FakeTelegramSender,
)
from tests.fakes.identity.uow import FakeIdentityUnitOfWork, IdentityStore
from tests.fakes.tasks import FakeTaskKicker
from tests.identity.support import World

from argon2 import PasswordHasher, profiles


def build_world(
    settings: Settings,
    i18n: I18nCore,
    redis: Any,
    clock: FixedClock,
    kicker: FakeTaskKicker,
) -> World:
    """Wire build_auth with fake Hydra, senders and an in-memory unit of work."""
    store = IdentityStore()
    hydra = FakeHydra()
    otp = FakeOtpSender()
    email = FakeEmailSender()
    telegram = FakeTelegramSender()
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=cast(Any, None),
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    auth = build_auth(
        deps,
        hydra=hydra,
        telegram_sender=telegram,
        email_sender=email,
        otp_sender=otp,
        hasher=Argon2PasswordHasher(PasswordHasher.from_parameters(profiles.CHEAPEST)),
        uow_factory=lambda: FakeIdentityUnitOfWork(store, clock),
    )
    return World(
        auth=auth,
        store=store,
        hydra=hydra,
        otp=otp,
        email=email,
        clock=clock,
        redis=redis,
        kicker=kicker,
        telegram=telegram,
    )
