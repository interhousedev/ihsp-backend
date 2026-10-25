"""ID-EMIS-LOGIN: login with an EMIS ID resolves server-side, with generic errors.

An unknown or malformed EMIS ID must fail exactly like a wrong password, so the
client learns nothing about who is registered, and the limits still apply.
"""

from app.modules.identity.application.log_in_with_emis_id import LogInWithEmisId
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.resolve_emis_login import ResolveEmisLogin
from app.modules.identity.domain.emis_login import emis_id_fingerprint
from app.modules.identity.domain.errors import InvalidCredentialsError
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError
from app.shared.rate_limit import RateLimiter
from tests.fakes.clock import FixedClock
from tests.fakes.identity.uow import FakeIdentityUnitOfWork
from tests.identity.emis.fakes import (
    FakeEmisUnitOfWork,
    InMemoryAccountRepository,
    Ledger,
)
from tests.identity.support import PASSWORD, World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest/1.0")
TEACHER_EMIS_ID = "78201"


def make_login(world: World) -> LogInWithEmisId:
    """The EMIS login over the world's password use case and identity users."""
    repo = InMemoryAccountRepository()
    ledger = Ledger()
    resolver = ResolveEmisLogin(
        uow_factory=lambda: FakeEmisUnitOfWork(repo, ledger),
        teacher_uow_factory=lambda: FakeIdentityUnitOfWork(world.store, FixedClock()),
        rate_limiter=RateLimiter(world.redis),
        floor_seconds=0.0,
    )
    return LogInWithEmisId(resolver=resolver, password=world.auth.log_in_with_password)


async def test_only_the_failed_login_is_counted_against_the_emis_id(
    auth_world: World,
) -> None:
    """ID-EMIS-LOGIN: lookups leave the ID counter alone; a wrong password adds one."""
    await add_teacher(auth_world)
    key = f"rl:emis-login-id:{emis_id_fingerprint(TEACHER_EMIS_ID)}"
    login = make_login(auth_world)
    auth_world.hydra.add_login("lc-2", client_id="sp")

    await login.resolver.find_login(TEACHER_EMIS_ID, ctx=CTX)
    assert await auth_world.redis.get(key) is None

    with pytest.raises(InvalidCredentialsError):
        await login.execute("lc-2", TEACHER_EMIS_ID, "wrong", remember=True, ctx=CTX)
    assert int(await auth_world.redis.get(key)) == 1


async def add_teacher(world: World) -> None:
    """A teacher with an EMIS teacher ID and a known password."""
    await world.add_user(
        login="karimova.dilnoza",
        roles={Role.TEACHER},
        emis_teacher_id=int(TEACHER_EMIS_ID),
    )


async def test_correct_password_with_registered_emis_id_signs_in(
    auth_world: World,
) -> None:
    """ID-EMIS-LOGIN: the password step runs for the account behind the EMIS ID."""
    await add_teacher(auth_world)
    auth_world.hydra.add_login("lc-1", client_id="sp")

    result = await make_login(auth_world).execute(
        "lc-1", TEACHER_EMIS_ID, PASSWORD, remember=True, ctx=CTX
    )

    assert result.redirect_to == "https://hydra/continue?login_verifier=lc-1"


async def test_wrong_password_with_registered_emis_id_is_invalid_credentials(
    auth_world: World,
) -> None:
    """ID-EMIS-LOGIN: a wrong password gives the ordinary generic error."""
    await add_teacher(auth_world)
    auth_world.hydra.add_login("lc-1", client_id="sp")

    with pytest.raises(InvalidCredentialsError):
        await make_login(auth_world).execute(
            "lc-1", TEACHER_EMIS_ID, "wrong-pass", remember=True, ctx=CTX
        )


async def test_unknown_emis_id_fails_like_a_wrong_password(auth_world: World) -> None:
    """ID-EMIS-LOGIN: no account and a wrong password raise the same error."""
    auth_world.hydra.add_login("lc-1", client_id="sp")

    with pytest.raises(InvalidCredentialsError) as unknown:
        await make_login(auth_world).execute(
            "lc-1", "90001", PASSWORD, remember=True, ctx=CTX
        )

    assert unknown.value.code == "auth/invalid-credentials"
    assert unknown.value.params == {}


async def test_malformed_emis_id_fails_like_a_wrong_password(auth_world: World) -> None:
    """ID-EMIS-LOGIN: a malformed ID is not a 422; it gets the generic error."""
    auth_world.hydra.add_login("lc-1", client_id="sp")

    with pytest.raises(InvalidCredentialsError):
        await make_login(auth_world).execute(
            "lc-1", "abc", PASSWORD, remember=True, ctx=CTX
        )


async def test_emis_login_is_rate_limited_per_ip(auth_world: World) -> None:
    """ID-EMIS-LOGIN: the sixth EMIS attempt in a minute from one IP is refused."""
    auth_world.hydra.add_login("lc-1", client_id="sp")
    login = make_login(auth_world)
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await login.execute("lc-1", "90001", "x", remember=True, ctx=CTX)

    with pytest.raises(RateLimitedError):
        await login.execute("lc-1", "90001", "x", remember=True, ctx=CTX)
