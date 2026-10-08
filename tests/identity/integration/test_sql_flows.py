"""build_auth over the real unit of work: the main flows against PostgreSQL."""

from dataclasses import dataclass
from typing import Any

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import InvalidCredentialsError
from app.modules.identity.domain.user import User
from app.modules.identity.infrastructure.argon2_hasher import Argon2PasswordHasher
from app.modules.identity.infrastructure.audit_writer import write_audit_events
from app.modules.identity.wiring_auth import build_auth
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.identity.hydra import FakeHydra
from tests.fakes.identity.senders import FakeEmailSender, FakeOtpSender
from tests.fakes.outbox import InMemoryOutbox
from tests.fakes.tasks import FakeTaskKicker
from tests.identity.integration.test_repositories import user_row
from tests.identity.support import PASSWORD

import pytest
from argon2 import PasswordHasher, profiles
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


@dataclass
class Rig:
    """The wired services and the fakes around them."""

    auth: Any
    hydra: FakeHydra
    otp: FakeOtpSender
    email: FakeEmailSender
    clock: FixedClock


@pytest.fixture
def sql_auth(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    outbox: InMemoryOutbox,
) -> Rig:
    """Wiring with the SQL unit of work, fake Hydra and senders."""
    hydra = FakeHydra()
    otp = FakeOtpSender()
    email = FakeEmailSender()
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker_in_tx,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=outbox.write_notifications,
        audit_writer=write_audit_events,
        outbox_committed_hook=None,
    )
    auth = build_auth(
        deps,
        hydra=hydra,
        email_sender=email,
        otp_sender=otp,
        hasher=Argon2PasswordHasher(PasswordHasher.from_parameters(profiles.CHEAPEST)),
    )
    return Rig(auth, hydra, otp, email, clock)


async def add_user(auth: Any, **fields: Any) -> User:
    """Insert a user with the test password."""
    user = user_row(**fields)
    user.password_hash = await auth.hasher.hash(PASSWORD)
    async with auth.uow_factory() as uow:
        await uow.users.add(user)
        await uow.commit()
    return user


async def test_login_block_and_epoch_against_postgres(sql_auth: Rig) -> None:
    """ID-16, GEN-5: a real session row, then a block bumps the epoch and revokes it."""
    auth, hydra = sql_auth.auth, sql_auth.hydra
    admin = await add_user(auth, roles={Role.ADMIN}, otp_enabled=True)
    user = await add_user(auth)
    hydra.add_login("lc-1")

    result = await auth.log_in_with_password.execute(
        "lc-1", user.login, PASSWORD, remember=True, ctx=CTX
    )
    assert result.redirect_to

    async with auth.uow_factory() as uow:
        (session,) = await uow.sessions.list_active(user.id, sql_auth.clock.now())
        assert session.hydra_sid == "hydra-sid-lc-1"
        assert (session.ip, session.user_agent) == ("203.0.113.5", "pytest")
        stored = await uow.users.get(user.id)
        assert stored.last_login_at is not None

    await auth.block_user.execute(
        Actor(user_id=admin.id, roles=frozenset({Role.ADMIN})), user.id, "spam", CTX
    )

    async with auth.uow_factory() as uow:
        assert await uow.sessions.list_active(user.id, sql_auth.clock.now()) == []
        assert (await uow.users.get_epoch(user.id)) == 2  # block + revoke_in
        events = await uow.audit_events.recent_for_user(user.id, 10)
    assert [e.type for e in events] == ["user.blocked", "login.success"]
    with pytest.raises(InvalidCredentialsError):
        hydra.add_login("lc-2")
        await auth.log_in_with_password.execute(
            "lc-2", user.login, PASSWORD, remember=False, ctx=CTX
        )


async def test_failed_login_audit_and_notification_are_committed(
    sql_auth: Rig, outbox: InMemoryOutbox
) -> None:
    """ID-15: failure bookkeeping survives the error."""
    auth, hydra = sql_auth.auth, sql_auth.hydra
    user = await add_user(auth)
    hydra.add_login("lc-1")

    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await auth.log_in_with_password.execute(
                "lc-1", user.login, "nope", remember=False, ctx=CTX
            )

    async with auth.uow_factory() as uow:
        events = await uow.audit_events.recent_for_user(user.id, 10)
    assert [e.type for e in events] == ["login.failed"] * 5
    assert [n.type.value for n in outbox.notifications] == ["login_failures"]


async def test_preferences_patch_is_one_sql_update(sql_auth: Rig) -> None:
    """Models: preferences || patch."""
    auth = sql_auth.auth
    user = await add_user(auth, preferences={"locale": "uz"})
    actor = Actor(user_id=user.id, roles=frozenset({Role.STUDENT}))

    result = await auth.update_preferences.execute(actor, {"theme": "dark"})

    assert (result.locale, result.theme) == ("uz", "dark")


async def test_teacher_creation_and_activation_on_postgres(sql_auth: Rig) -> None:
    """ID-10: pending account, hashed token, activation with a confirmed email."""
    auth, email = sql_auth.auth, sql_auth.email
    admin = await add_user(auth, roles={Role.ADMIN}, otp_enabled=True)

    created = await auth.create_teacher.execute(
        admin.id,
        last_name="Kalandarova",
        first_name="Gavxar",
        middle_name=None,
        email="t@example.org",
        ctx=CTX,
    )
    token = created.activation_url.split("token=")[1]
    await auth.activation_send_email_code.execute(token, "me@example.org", CTX)
    redirect = await auth.activate_account.execute(
        token,
        password="N3wStrongPass",
        email="me@example.org",
        email_code=email.last_code("me@example.org"),
        ctx=CTX,
    )

    assert redirect == "http://localhost:3003"
    async with auth.uow_factory() as uow:
        teacher = await uow.users.get_by_login("kalandarova.gavxar")
    assert (
        teacher.status.value == "active" and teacher.recovery_email == "me@example.org"
    )
    assert teacher.roles == {Role.TEACHER} and teacher.activation_token_hash is None
