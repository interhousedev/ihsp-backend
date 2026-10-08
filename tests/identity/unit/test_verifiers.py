"""GEN-5, MCP-5: access token and connector token verification."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from app.modules.identity.infrastructure.access_token_verifier import (
    HydraAccessTokenVerifier,
)
from app.modules.identity.infrastructure.redis.auth_epoch_cache import (
    RedisAuthEpochCache,
)
from app.modules.identity.infrastructure.redis.revocation_list import (
    RedisRevocationList,
)
from app.shared.actor import Role
from app.shared.base_error import UnauthorizedError
from app.shared.ids import hash_token, new_id
from tests.identity.support import World

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

ISSUER = "http://localhost:4444"


class StubJwks:
    """JwksCache replacement that serves a fixed key set."""

    def __init__(self, keys: KeySet) -> None:
        """Keep the key set."""
        self.keys = keys
        self.forced = 0

    async def key_set(self, *, force: bool = False) -> KeySet:
        """Return the key set; count forced refetches."""
        self.forced += int(force)
        return self.keys


class TokenFactory:
    """Signs Hydra-shaped access tokens."""

    def __init__(self, world: World) -> None:
        """Create the signing key and a verifier over the world's stores."""
        self.key = RSAKey.generate_key(2048, parameters={"kid": "k1", "use": "sig"})
        self.jwks = StubJwks(KeySet([self.key]))
        self.world = world
        self.verifier = HydraAccessTokenVerifier(
            jwks=self.jwks,  # type: ignore[arg-type]
            issuer=ISSUER,
            epochs=RedisAuthEpochCache(world.redis),
            revocations=RedisRevocationList(world.redis),
            load_epoch=self._load_epoch,
            clock=world.clock,
        )

    async def _load_epoch(self, user_id: UUID) -> int | None:
        user = self.world.store.users.get(user_id)
        return user.auth_epoch if user else None

    def token(
        self,
        user_id: UUID,
        *,
        audience: str = "ihsp-api",
        epoch: int = 0,
        sid: str | None = None,
        roles: tuple[str, ...] = ("student",),
        scp: list[str] | None = None,
        expires_in: int = 600,
        extra: dict[str, Any] | None = None,
        key: RSAKey | None = None,
        iss: str = ISSUER,
    ) -> str:
        """Sign a token like Hydra would, custom claims under `ext`."""
        now = int(self.world.clock.now().timestamp())
        claims = {
            "iss": iss,
            "sub": str(user_id),
            "aud": [audience, "http://localhost:4444/oauth2/token"],
            "client_id": "sp",
            "scp": scp or ["openid"],
            "iat": now,
            "exp": now + expires_in,
            "jti": str(new_id()),
            "ext": {
                "auth_epoch": epoch,
                "roles": list(roles),
                "amr": ["pwd"],
                "mfa_at": None,
                "sid": sid or str(new_id()),
                **(extra or {}),
            },
        }
        signer = key or self.key
        return jwt.encode({"alg": "RS256", "kid": signer.kid}, claims, signer)


@pytest.fixture
def tokens(auth_world: World) -> TokenFactory:
    """A token factory bound to the world."""
    return TokenFactory(auth_world)


async def test_valid_token_gives_the_actor(
    auth_world: World, tokens: TokenFactory
) -> None:
    """ID-16: roles, session, amr and client come from the token."""
    user = await auth_world.add_user(auth_epoch=2)
    sid = new_id()

    actor = await tokens.verifier.verify(
        tokens.token(user.id, epoch=2, sid=str(sid), roles=("student", "admin")),
        audience="ihsp-api",
    )

    assert actor.user_id == user.id
    assert actor.roles == {Role.STUDENT, Role.ADMIN}
    assert actor.session_id == sid
    assert actor.client_id == "sp"
    assert actor.amr == {"pwd"}
    assert actor.scopes == frozenset()


@pytest.mark.parametrize("iss", ["http://localhost:4444", "http://localhost:4444/"])
async def test_issuer_is_accepted_with_or_without_trailing_slash(
    auth_world: World, tokens: TokenFactory, iss: str
) -> None:
    """Hydra signs `iss` as configured: both forms of the issuer are the same issuer."""
    user = await auth_world.add_user()

    actor = await tokens.verifier.verify(
        tokens.token(user.id, iss=iss), audience="ihsp-api"
    )

    assert actor.user_id == user.id


async def test_other_issuer_is_unauthorized(
    auth_world: World, tokens: TokenFactory
) -> None:
    """A token of another issuer is refused."""
    user = await auth_world.add_user()

    with pytest.raises(UnauthorizedError):
        await tokens.verifier.verify(
            tokens.token(user.id, iss="http://evil.example/"), audience="ihsp-api"
        )


async def test_expired_token_is_unauthorized(
    auth_world: World, tokens: TokenFactory
) -> None:
    """ID-16: expired tokens are refused."""
    user = await auth_world.add_user()
    token = tokens.token(user.id, expires_in=60)
    auth_world.clock.advance(minutes=2)

    with pytest.raises(UnauthorizedError):
        await tokens.verifier.verify(token, audience="ihsp-api")


async def test_wrong_audience_is_unauthorized(
    auth_world: World, tokens: TokenFactory
) -> None:
    """ID-16: tokens are bound to their audience."""
    user = await auth_world.add_user()

    with pytest.raises(UnauthorizedError):
        await tokens.verifier.verify(
            tokens.token(user.id, audience="mcp-student"), audience="ihsp-api"
        )


async def test_token_signed_by_another_key_is_unauthorized(
    auth_world: World, tokens: TokenFactory
) -> None:
    """The signature must match a key published by Hydra."""
    user = await auth_world.add_user()
    forger = RSAKey.generate_key(2048, parameters={"kid": "k1"})

    with pytest.raises(UnauthorizedError):
        await tokens.verifier.verify(
            tokens.token(user.id, key=forger), audience="ihsp-api"
        )


async def test_unknown_key_id_refetches_the_jwks_once(
    auth_world: World, tokens: TokenFactory
) -> None:
    """Key rotation: an unknown kid triggers one forced refetch, then a refusal."""
    user = await auth_world.add_user()
    stranger = RSAKey.generate_key(2048, parameters={"kid": "rotated"})

    with pytest.raises(UnauthorizedError):
        await tokens.verifier.verify(
            tokens.token(user.id, key=stranger), audience="ihsp-api"
        )

    assert tokens.jwks.forced == 1


async def test_revoked_session_is_unauthorized_on_the_next_request(
    auth_world: World, tokens: TokenFactory
) -> None:
    """ID-17: revocation applies at once through the Redis list."""
    user = await auth_world.add_user()
    sid = new_id()
    await RedisRevocationList(auth_world.redis).revoke(sid)

    with pytest.raises(UnauthorizedError):
        await tokens.verifier.verify(
            tokens.token(user.id, sid=str(sid)), audience="ihsp-api"
        )


async def test_stale_auth_epoch_is_unauthorized(
    auth_world: World, tokens: TokenFactory
) -> None:
    """GEN-5: after a block or role change older tokens stop working."""
    user = await auth_world.add_user(auth_epoch=3)
    await RedisAuthEpochCache(auth_world.redis).set(user.id, 3)

    with pytest.raises(UnauthorizedError):
        await tokens.verifier.verify(
            tokens.token(user.id, epoch=2), audience="ihsp-api"
        )


async def test_epoch_cache_is_refreshed_from_the_database(
    auth_world: World, tokens: TokenFactory
) -> None:
    """A stale cache entry heals itself: tokens with the new epoch work again."""
    user = await auth_world.add_user(auth_epoch=5)
    cache = RedisAuthEpochCache(auth_world.redis)
    await cache.set(user.id, 4)

    await tokens.verifier.verify(tokens.token(user.id, epoch=5), audience="ihsp-api")

    assert await cache.get(user.id) == 5


async def test_token_of_an_unknown_user_is_unauthorized(
    auth_world: World, tokens: TokenFactory
) -> None:
    """A deleted user's tokens are refused."""
    with pytest.raises(UnauthorizedError):
        await tokens.verifier.verify(tokens.token(new_id()), audience="ihsp-api")


@pytest.mark.parametrize("audience", ["mcp-student", "mcp-lms", "mcp-admin"])
async def test_mcp_audience_tokens_carry_scp_scopes_and_the_connector(
    auth_world: World, tokens: TokenFactory, audience: str
) -> None:
    """B15: Actor.scopes comes from `scp` for the MCP audiences."""
    user = await auth_world.add_user()
    connector_id = new_id()

    actor = await tokens.verifier.verify(
        tokens.token(
            user.id,
            audience=audience,
            sid=str(connector_id),
            scp=["openid", "schedule:read", "marks:read"],
            extra={"connector_id": str(connector_id)},
        ),
        audience=audience,
    )

    assert actor.connector_id == connector_id
    assert actor.session_id is None
    assert actor.scopes == {"openid", "schedule:read", "marks:read"}


async def test_revoked_connector_token_is_unauthorized(
    auth_world: World, tokens: TokenFactory
) -> None:
    """UF-MCP-04: the connector id is on the revocation list after revoking."""
    user = await auth_world.add_user()
    connector_id = new_id()
    await RedisRevocationList(auth_world.redis).revoke(connector_id)

    with pytest.raises(UnauthorizedError):
        await tokens.verifier.verify(
            tokens.token(
                user.id,
                audience="mcp-student",
                sid=str(connector_id),
                extra={"connector_id": str(connector_id)},
            ),
            audience="mcp-student",
        )


async def test_connector_token_gives_scopes_for_its_server(auth_world: World) -> None:
    """MCP-5: a valid token connector becomes an actor with its scopes."""
    user = await auth_world.add_user()
    token = "ihsp_mcp_" + "a" * 43
    connector = auth_world.add_connector(
        user,
        token_hash=hash_token(token),
        scopes=["schedule:read", "homework:read"],
        expires_at=auth_world.clock.now() + timedelta(days=30),
    )

    actor = await auth_world.auth.connector_verifier.verify_connector(
        token, server="student"
    )

    assert actor.user_id == user.id
    assert actor.connector_id == connector.id
    assert actor.scopes == {"schedule:read", "homework:read"}
    assert auth_world.store.connectors[connector.id].last_used_at is not None


@pytest.mark.parametrize(
    "change",
    [
        {"revoked_at": "now"},
        {"expires_at": "past"},
        {"server": "lms"},
    ],
)
async def test_revoked_expired_or_wrong_server_connector_is_unauthorized(
    auth_world: World, change: dict[str, str]
) -> None:
    """MCP-5: every call re-checks the connector."""
    user = await auth_world.add_user()
    token = "ihsp_mcp_" + "b" * 43
    fields: dict[str, Any] = {
        "token_hash": hash_token(token),
        "expires_at": auth_world.clock.now() + timedelta(days=30),
    }
    for key, value in change.items():
        if value == "now":
            fields[key] = auth_world.clock.now()
        elif value == "past":
            fields[key] = auth_world.clock.now() - timedelta(seconds=1)
        else:
            fields[key] = value
    auth_world.add_connector(user, **fields)

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.connector_verifier.verify_connector(
            token, server="student"
        )


async def test_connector_of_a_blocked_user_is_unauthorized(auth_world: World) -> None:
    """GEN-5: blocking stops the user's connectors."""
    from app.shared.contracts.identity import UserStatus

    user = await auth_world.add_user(status=UserStatus.BLOCKED)
    token = "ihsp_mcp_" + "c" * 43
    auth_world.add_connector(user, token_hash=hash_token(token))

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.connector_verifier.verify_connector(
            token, server="student"
        )


async def test_connector_of_a_user_who_lost_the_role_is_unauthorized(
    auth_world: World,
) -> None:
    """MCP-5: the role is still checked at call time."""
    teacher = await auth_world.add_user(roles={Role.TEACHER})
    token = "ihsp_mcp_" + "d" * 43
    auth_world.add_connector(
        teacher, token_hash=hash_token(token), server="admin", scopes=["people:read"]
    )

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.connector_verifier.verify_connector(token, server="admin")


async def test_lms_connector_restricted_to_courses_exposes_course_scopes(
    auth_world: World,
) -> None:
    """B15: course restrictions travel as course:<uuid> scopes."""
    teacher = await auth_world.add_user(roles={Role.TEACHER})
    course_a, course_b = new_id(), new_id()
    token = "ihsp_mcp_" + "e" * 43
    auth_world.add_connector(
        teacher,
        token_hash=hash_token(token),
        server="lms",
        scopes=["courses:read", "courses:draft"],
        course_ids=[course_a, course_b],
    )

    actor = await auth_world.auth.connector_verifier.verify_connector(
        token, server="lms"
    )

    assert actor.scopes == {
        "courses:read",
        "courses:draft",
        f"course:{course_a}",
        f"course:{course_b}",
    }


async def test_lms_connector_for_all_courses_has_no_course_scopes(
    auth_world: World,
) -> None:
    """MCP-2: without course_ids the connector covers every editable course."""
    teacher = await auth_world.add_user(roles={Role.TEACHER})
    token = "ihsp_mcp_" + "f" * 43
    auth_world.add_connector(
        teacher, token_hash=hash_token(token), server="lms", scopes=["courses:read"]
    )

    actor = await auth_world.auth.connector_verifier.verify_connector(
        token, server="lms"
    )

    assert actor.scopes == {"courses:read"}


async def test_token_without_the_connector_prefix_is_unauthorized(
    auth_world: World,
) -> None:
    """Cheap format check before the database lookup."""
    with pytest.raises(UnauthorizedError):
        await auth_world.auth.connector_verifier.verify_connector(
            "not-a-token", server="student"
        )
