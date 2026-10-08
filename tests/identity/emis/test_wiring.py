"""build_emis wires every use case of task B2."""

from dataclasses import fields

from app.modules.identity.infrastructure.emis.fake import FakeEmisClient
from app.modules.identity.wiring_emis import EmisServices, build_emis
from app.settings import Settings
from app.shared.db.engine import make_engine, make_sessionmaker
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.identity.vault import InMemoryCredentialStore
from tests.fakes.tasks import FakeTaskKicker
from tests.identity.emis.fakes import (
    FakeAccountRevoker,
    FakeEmailSender,
    FakeEnrollment,
    FakeLoginAcceptor,
    FakeOtpStore,
)

from fakeredis.aioredis import FakeRedis

EXPECTED = {
    "gateway",
    "register_start",
    "register_email_code",
    "register_complete",
    "reclaim_start",
    "reclaim_email_code",
    "reclaim_complete",
    "update_emis_password",
    "delete_account",
    "destroy_emis_secret",
}


def make_deps(settings: Settings, redis: FakeRedis, i18n: I18nCore) -> ModuleDeps:
    engine = make_engine(settings.database.url, pool_size=1)
    return ModuleDeps(
        settings=settings,
        clock=FixedClock(),
        redis=redis,
        sessionmaker=make_sessionmaker(engine),
        kicker=FakeTaskKicker(),
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )


def build(deps: ModuleDeps, emis_client: FakeEmisClient | None = None) -> EmisServices:
    return build_emis(
        deps,
        login_acceptor=FakeLoginAcceptor(),
        account_revoker=FakeAccountRevoker(),
        email_sender=FakeEmailSender(),
        otp_store=FakeOtpStore(),
        academic_enrollment=FakeEnrollment(),
        credentials=InMemoryCredentialStore(),
        emis_client=emis_client,
    )


async def test_every_use_case_is_built_with_the_fake_emis(
    settings: Settings, redis: FakeRedis, i18n: I18nCore
) -> None:
    """§ 3.12: ``container.identity.emis.<use_case>`` and ``.gateway``."""
    services = build(make_deps(settings, redis, i18n))

    names = {f.name for f in fields(services)} - {"closers"}
    assert names == EXPECTED
    assert all(getattr(services, name) is not None for name in EXPECTED)
    assert services.closers == []


async def test_real_mode_builds_the_http_client_and_closes_it(
    settings: Settings, redis: FakeRedis, i18n: I18nCore
) -> None:
    """EMIS__MODE=real: the HTTP client is created lazily and closed by close()."""
    real = settings.model_copy(
        update={"emis": settings.emis.model_copy(update={"mode": "real"})}
    )

    services = build(make_deps(real, redis, i18n))

    assert len(services.closers) == 1
    await services.close()


async def test_an_injected_client_replaces_the_mode_choice(
    settings: Settings, redis: FakeRedis, i18n: I18nCore
) -> None:
    """Tests and I1 can pass their own EMIS client."""
    deps = make_deps(settings, redis, i18n)

    services = build(deps, FakeEmisClient(FixedClock()))

    assert services.closers == []
