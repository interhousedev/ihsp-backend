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

    async def consented(_user_id: object, _app: str = "global") -> None:
        return None

    container: Any = SimpleNamespace(
        identity=SimpleNamespace(
            personal_token_verifier=world.auth.personal_token_verifier
        ),
        legal=SimpleNamespace(require_consent=SimpleNamespace(execute=consented)),
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


async def test_admission_tokens_expire_within_90_days(auth_world: World) -> None:
    """An admission scope caps the expiry; the token stops working when it ends."""
    user = await auth_world.add_user(roles={Role.STUDENT})
    with pytest.raises(PersonalTokenInvalidError):
        await create(auth_world, user, scopes=["admission:read"], expires_in_days=365)
    created = await create(
        auth_world, user, scopes=["admission:read"], expires_in_days=90
    )
    verifier = auth_world.auth.personal_token_verifier
    actor = await verifier.verify_personal(created.secret)
    assert actor.scopes == frozenset({"admission:read"})
    auth_world.clock.advance(days=91)
    with pytest.raises(UnauthorizedError):
        await verifier.verify_personal(created.secret)


async def test_admission_erase_revokes_only_admission_tokens(
    auth_world: World,
) -> None:
    """Erasing admission data stops the user's admission tokens, not the others."""
    user = await auth_world.add_user(roles={Role.STUDENT})
    other = await auth_world.add_user(login="other.user", roles={Role.STUDENT})
    admission = await create(
        auth_world, user, scopes=["admission:documents"], expires_in_days=90
    )
    plain = await create(auth_world, user)
    foreign = await create(
        auth_world, other, scopes=["admission:read"], expires_in_days=90
    )

    await auth_world.auth.revoke_admission_tokens.execute(user.id)

    verifier = auth_world.auth.personal_token_verifier
    with pytest.raises(UnauthorizedError):
        await verifier.verify_personal(admission.secret)
    await verifier.verify_personal(plain.secret)
    await verifier.verify_personal(foreign.secret)


_UID = "0191d7a2-1b2c-7d3e-8f40-123456789abc"
CATALOG = ["admission:catalog"]


@pytest.mark.parametrize(
    "roles", [{Role.TEACHER}, {Role.COUNSELOR}, {Role.STUDENT, Role.TEACHER}]
)
async def test_staff_create_catalog_tokens_up_to_90_days(
    auth_world: World, roles: set[Role]
) -> None:
    """ADM-INTL-3: a non-student account issues a catalog-only token (≤ 90 days)."""
    user = await auth_world.add_user(roles=roles)

    created = await create(auth_world, user, scopes=CATALOG, expires_in_days=90)

    assert list(created.token.scopes) == CATALOG


@pytest.mark.parametrize(
    ("roles", "overrides", "field"),
    [
        ({Role.STUDENT}, {"scopes": CATALOG}, "scopes"),
        ({Role.TEACHER}, {"scopes": [*CATALOG, "me:read"]}, "scopes"),
        ({Role.TEACHER}, {"scopes": [*CATALOG, "admission:read"]}, "scopes"),
        (
            {Role.TEACHER},
            {"scopes": CATALOG, "expires_in_days": 365},
            "expires_in_days",
        ),
    ],
)
async def test_catalog_token_rules_are_enforced(
    auth_world: World, roles: set[Role], overrides: dict[str, Any], field: str
) -> None:
    """ADM-INTL-3: catalog alone, staff owners only, at most 90 days."""
    user = await auth_world.add_user(roles=roles)

    with pytest.raises(PersonalTokenInvalidError) as caught:
        await create(auth_world, user, **overrides)

    assert field in caught.value.params["fields"]
    assert auth_world.store.personal_tokens == {}


async def test_catalog_token_still_needs_the_step_up_code(auth_world: World) -> None:
    """ADM-INTL-3: the OTP step-up is unchanged for catalog tokens."""
    user = await auth_world.add_user(roles={Role.COUNSELOR})

    with pytest.raises(SecondFactorRequiredError):
        await create(auth_world, user, scopes=CATALOG, otp_code=None)


@pytest.mark.parametrize("days", [7, 0, 365])
async def test_catalog_token_expiry_must_be_30_or_90_days(
    auth_world: World, days: int
) -> None:
    """ADM-INTL-SEC-7: 7, 0 (no expiry) and 365 days are refused for a catalog token."""
    user = await auth_world.add_user(roles={Role.COUNSELOR})

    with pytest.raises(PersonalTokenInvalidError) as caught:
        await create(auth_world, user, scopes=CATALOG, expires_in_days=days)

    assert "expires_in_days" in caught.value.params["fields"]
    assert auth_world.store.personal_tokens == {}


_CATALOG_ALLOWED = [
    ("GET", "/v1/admission/catalog/institutions"),
    ("GET", f"/v1/admission/catalog/institutions/{_UID}"),
    ("GET", "/v1/admission/catalog/scholarships"),
    ("GET", "/v1/admission/catalog/facets"),
    ("GET", "/v1/admission/catalog/study-fields"),
    ("GET", f"/v1/admission/catalog/institutions/{_UID}/supp-prompts"),
    ("GET", f"/v1/admission/staff/catalog/institutions/{_UID}"),
    ("GET", "/v1/admission/staff/catalog/fact-spec"),
    ("GET", "/v1/admission/staff/catalog/proposals"),
    ("POST", "/v1/admission/staff/catalog/proposals"),
]
_CATALOG_REFUSED = [
    ("POST", f"/v1/admission/staff/catalog/proposals/{_UID}/review"),
    ("DELETE", "/v1/admission/staff/catalog/proposals"),
    ("PATCH", f"/v1/admission/staff/catalog/institutions/{_UID}"),  # logo edit
    ("PUT", f"/v1/admission/staff/catalog/institutions/{_UID}/supp-prompts/2026-27"),
    ("POST", f"/v1/admission/catalog/institutions/{_UID}/summary"),
    ("POST", "/v1/admission/catalog/institutions"),
    ("GET", f"/v1/admission/catalog/institutions/{_UID}/extra"),
    ("GET", "/v1/admission/catalog/institutionsX"),
    ("GET", "/v1/admission/catalog/institutions/../../students"),
    ("GET", f"/v1/admission/students/{_UID}/list"),
    ("GET", "/v1/admission/me"),
    ("GET", "/v1/me"),
    ("GET", "/v1/me/profile"),
    ("PATCH", "/v1/me/profile"),
]


async def test_catalog_token_reaches_only_the_allowlist(auth_world: World) -> None:
    """ADM-INTL-3: a catalog token passes the allowlist and nothing else."""
    user = await auth_world.add_user(roles={Role.COUNSELOR})
    created = await create(auth_world, user, scopes=CATALOG)

    for method, path in _CATALOG_ALLOWED:
        actor = await verify(auth_world, method, path, created.secret)
        assert actor.user_id == user.id
    for method, path in _CATALOG_REFUSED:
        with pytest.raises(TokenScopeError):
            await verify(auth_world, method, path, created.secret)


async def test_other_scopes_do_not_reach_the_catalog(auth_world: World) -> None:
    """ADM-INTL-3: me:* and admission MCP tokens are refused on catalog routes."""
    user = await auth_world.add_user(roles={Role.STUDENT, Role.TEACHER})
    me = await create(auth_world, user, scopes=["me:read", "me:write"])
    admission = await create(auth_world, user, scopes=["admission:read"])

    for token in (me.secret, admission.secret):
        for method, path in _CATALOG_ALLOWED:
            with pytest.raises(TokenScopeError):
                await verify(auth_world, method, path, token)
    await verify(auth_world, "GET", "/v1/me", me.secret)
