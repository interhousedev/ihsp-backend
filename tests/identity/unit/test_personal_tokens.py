"""Personal API tokens: issue (OTP step-up), verify, scope check, revoke."""

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.http.dependencies import _verify
from app.modules.identity.application.personal_tokens import NewPersonalToken
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    PersonalTokenInvalidError,
    SecondFactorRequiredError,
    TokenScopeError,
)
from app.modules.identity.domain.personal_token import PersonalToken
from app.modules.identity.domain.user import User
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError, UnauthorizedError
from app.shared.contracts.identity import UserStatus
from app.shared.ids import hash_token, new_id
from tests.identity.support import World

import pytest
from starlette.requests import Request

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


def actor_of(user: User) -> Actor:
    """The caller."""
    return Actor(user_id=user.id, roles=frozenset(user.roles))


async def create(world: World, user: User, **overrides: Any) -> NewPersonalToken:
    """Create a token after a step-up (the code cooldown is cleared)."""
    await world.redis.delete(f"otp:cooldown:step-up:{user.id}")
    await world.auth.step_up.execute(actor_of(user), CTX)
    args: dict[str, Any] = {
        "name": "CLI",
        "scopes": ["me:read"],
        "expires_in_days": 30,
        "otp_code": world.otp.last("step-up").code,
        "ctx": CTX,
    }
    args.update(overrides)
    return await world.auth.create_personal_token.execute(actor_of(user), **args)


def request_of(method: str, path: str) -> Request:
    """A bare request."""
    return Request({"type": "http", "method": method, "path": path, "headers": []})


async def verify(world: World, method: str, path: str, token: str) -> Actor:
    """Run the same check as get_actor."""
    container: Any = SimpleNamespace(
        identity=SimpleNamespace(
            personal_token_verifier=world.auth.personal_token_verifier
        )
    )
    return await _verify(container, request_of(method, path), token)


async def test_token_is_shown_once_and_only_its_hash_is_stored(
    auth_world: World,
) -> None:
    """The secret has the prefix; the store keeps its hash and an 8 char prefix."""
    user = await auth_world.add_user()

    created = await create(auth_world, user, scopes=["me:read", "me:read"])

    assert created.secret.startswith("ihsp_pat_")
    stored = auth_world.store.personal_tokens[created.token.id]
    assert stored.token_hash == hash_token(created.secret)
    assert created.secret not in repr(stored)
    assert stored.prefix == created.secret[len("ihsp_pat_") :][: len(stored.prefix)]
    assert stored.scopes == ["me:read"]
    assert stored.expires_at == auth_world.clock.now() + timedelta(days=30)
    assert "personal_token.created" in auth_world.store.audit_types(user.id)
    audit_text = repr(auth_world.store.audits)
    assert created.secret not in audit_text


async def test_creating_needs_the_step_up_code(auth_world: World) -> None:
    """No code or a wrong code creates nothing."""
    user = await auth_world.add_user()
    with pytest.raises(SecondFactorRequiredError):
        await auth_world.auth.create_personal_token.execute(
            actor_of(user),
            name="CLI",
            scopes=["me:read"],
            expires_in_days=30,
            otp_code=None,
            ctx=CTX,
        )
    with pytest.raises(Exception):  # noqa: B017 - wrong code, any OTP error
        await create(auth_world, user, otp_code="000000x")
    assert auth_world.store.personal_tokens == {}


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "   "},
        {"name": "x" * 81},
        {"scopes": []},
        {"scopes": ["me:read", "admin:all"]},
        {"expires_in_days": 45},
        {"expires_in_days": 0},
    ],
)
async def test_invalid_requests_are_refused(
    auth_world: World, overrides: dict[str, Any]
) -> None:
    """Name, scopes and expiry are checked."""
    user = await auth_world.add_user()
    with pytest.raises(PersonalTokenInvalidError):
        await create(auth_world, user, **overrides)
    assert auth_world.store.personal_tokens == {}


async def test_list_shows_own_tokens_only(auth_world: World) -> None:
    """Listing is per user."""
    user = await auth_world.add_user()
    other = await auth_world.add_user(login="other.user")
    mine = await create(auth_world, user)
    await create(auth_world, other)

    listed = await auth_world.auth.list_personal_tokens.execute(actor_of(user))

    assert [t.id for t in listed] == [mine.token.id]


async def test_revoking_stops_the_token_and_is_idempotent(auth_world: World) -> None:
    """Revoked tokens give 401; a foreign token is not found."""
    user = await auth_world.add_user()
    other = await auth_world.add_user(login="other.user")
    created = await create(auth_world, user)
    await verify(auth_world, "GET", "/v1/me/profile", created.secret)

    with pytest.raises(NotFoundError):
        await auth_world.auth.revoke_personal_token.execute(
            actor_of(other), created.token.id, CTX
        )
    with pytest.raises(NotFoundError):
        await auth_world.auth.revoke_personal_token.execute(
            actor_of(user), UUID(int=new_id().int), CTX
        )
    await auth_world.auth.revoke_personal_token.execute(
        actor_of(user), created.token.id, CTX
    )
    await auth_world.auth.revoke_personal_token.execute(
        actor_of(user), created.token.id, CTX
    )

    with pytest.raises(UnauthorizedError):
        await verify(auth_world, "GET", "/v1/me/profile", created.secret)
    types = auth_world.store.audit_types(user.id)
    assert types.count("personal_token.revoked") == 1


async def test_expired_blocked_and_unknown_tokens_are_refused(
    auth_world: World,
) -> None:
    """401 for each."""
    user = await auth_world.add_user()
    created = await create(auth_world, user)

    with pytest.raises(UnauthorizedError):
        await verify(auth_world, "GET", "/v1/me/x", "ihsp_pat_" + "a" * 43)

    auth_world.store.users[user.id].status = UserStatus.BLOCKED
    with pytest.raises(UnauthorizedError):
        await verify(auth_world, "GET", "/v1/me/x", created.secret)
    auth_world.store.users[user.id].status = UserStatus.ACTIVE

    auth_world.clock.advance(days=31)
    with pytest.raises(UnauthorizedError):
        await verify(auth_world, "GET", "/v1/me/x", created.secret)


async def test_scopes_decide_the_paths_and_methods(auth_world: World) -> None:
    """me:read reads /v1/me/*, me:write writes it, anything else is 403."""
    user = await auth_world.add_user()
    reader = await create(auth_world, user)
    writer = await create(auth_world, user, scopes=["me:write"])

    actor = await verify(auth_world, "GET", "/v1/me/profile", reader.secret)
    assert actor.user_id == user.id
    await verify(auth_world, "HEAD", "/v1/me/profile", reader.secret)
    await verify(auth_world, "PATCH", "/v1/me/profile", writer.secret)
    for method, path, token in [
        ("POST", "/v1/me/profile", reader.secret),
        ("GET", "/v1/me/profile", writer.secret),
        ("GET", "/v1/schedule", reader.secret),
        ("GET", "/v1/id/personal-tokens", reader.secret),
        ("GET", "/v1/mex", reader.secret),
    ]:
        with pytest.raises(TokenScopeError) as caught:
            await verify(auth_world, method, path, token)
        assert caught.value.code == "id/token-scope"
        assert caught.value.status == 403


async def test_last_used_is_updated_at_most_once_a_minute(auth_world: World) -> None:
    """The throttle keeps the write off the hot path."""
    user = await auth_world.add_user()
    created = await create(auth_world, user)

    def stored() -> PersonalToken:
        return auth_world.store.personal_tokens[created.token.id]

    assert stored().last_used_at is None

    await verify(auth_world, "GET", "/v1/me/x", created.secret)
    first = stored().last_used_at
    assert first == auth_world.clock.now()

    auth_world.clock.advance(seconds=30)
    await verify(auth_world, "GET", "/v1/me/x", created.secret)
    assert stored().last_used_at == first

    auth_world.clock.advance(seconds=40)
    await verify(auth_world, "GET", "/v1/me/x", created.secret)
    assert stored().last_used_at == auth_world.clock.now()
    assert (
        Role.STUDENT
        in (await verify(auth_world, "GET", "/v1/me/x", created.secret)).roles
    )
