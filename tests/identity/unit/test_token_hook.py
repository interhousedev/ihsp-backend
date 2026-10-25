"""GEN-5, ID-16: Hydra's token hook refuses and refreshes claims on every issue."""

from typing import Any
from uuid import UUID

from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from tests.identity.support import World

JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"


def hook_payload(
    user_id: UUID,
    extra: dict[str, Any] | None = None,
    *,
    grant_types: list[str] | None = None,
    assertion: str | None = None,
) -> dict[str, Any]:
    """The body Hydra POSTs to the token hook."""
    request: dict[str, Any] = {
        "client_id": "sp",
        "grant_types": grant_types or ["refresh_token"],
    }
    if assertion:
        request["payload"] = {"assertion": [assertion]}
    return {
        "session": {
            "id_token": {
                "subject": str(user_id),
                "id_token_claims": {"sub": str(user_id)},
            },
            "extra": extra or {},
        },
        "request": request,
    }


async def test_active_user_gets_the_full_fresh_claim_set(auth_world: World) -> None:
    """ID-16: roles and the epoch come from the database, not from consent time."""
    user = await auth_world.add_user(roles={Role.STUDENT, Role.TEACHER}, auth_epoch=7)
    session = auth_world.add_session(user, amr=["pwd"])
    payload = hook_payload(
        user.id, {"sid": str(session.id), "amr": ["pwd"], "roles": ["student"]}
    )

    result = await auth_world.auth.handle_token_hook.execute(payload)

    assert result.action == "claims"
    assert result.session is not None
    assert result.session["access_token"] == {
        "auth_epoch": 7,
        "roles": ["student", "teacher"],
        "amr": ["pwd"],
        "mfa_at": None,
        "sid": str(session.id),
    }
    assert result.session["id_token"] == {"roles": ["student", "teacher"]}


async def test_blocked_user_is_denied(auth_world: World) -> None:
    """GEN-5: a blocked user gets no new tokens (Hydra answers access_denied)."""
    user = await auth_world.add_user(status=UserStatus.BLOCKED)
    session = auth_world.add_session(user)

    result = await auth_world.auth.handle_token_hook.execute(
        hook_payload(user.id, {"sid": str(session.id)})
    )

    assert result.action == "deny"


async def test_revoked_session_cannot_refresh(auth_world: World) -> None:
    """ID-17: revoking a session also stops its refresh tokens."""
    user = await auth_world.add_user()
    session = auth_world.add_session(user)
    session.revoked_at = auth_world.clock.now()

    result = await auth_world.auth.handle_token_hook.execute(
        hook_payload(user.id, {"sid": str(session.id)})
    )

    assert result.action == "deny"


async def test_session_of_another_user_is_denied(auth_world: World) -> None:
    """The sid in the consent session must belong to the subject."""
    user = await auth_world.add_user()
    other = await auth_world.add_user(
        login="other.user", recovery_email="o@example.org"
    )
    session = auth_world.add_session(other)

    result = await auth_world.auth.handle_token_hook.execute(
        hook_payload(user.id, {"sid": str(session.id)})
    )

    assert result.action == "deny"


async def test_request_without_a_subject_is_left_unchanged(auth_world: World) -> None:
    """Grants without a user (e.g. client credentials) get a 204."""
    result = await auth_world.auth.handle_token_hook.execute(
        {"session": {"id_token": {}, "extra": {}}, "request": {}}
    )

    assert result.action == "unchanged"


async def test_jwt_bearer_grant_reads_sid_and_amr_from_our_assertion(
    auth_world: World,
) -> None:
    """ID-19: mini app tokens carry sid and amr [tg] from the signed assertion."""
    user = await auth_world.add_user()
    session = auth_world.add_session(user, amr=["tg"])
    assertion = auth_world.auth.signer.sign(user.id, session.id, ["tg"])

    result = await auth_world.auth.handle_token_hook.execute(
        hook_payload(user.id, grant_types=[JWT_BEARER], assertion=assertion)
    )

    assert result.action == "claims"
    assert result.session is not None
    assert result.session["access_token"]["amr"] == ["tg"]
    assert result.session["access_token"]["sid"] == str(session.id)


async def test_jwt_bearer_grant_with_a_foreign_assertion_is_denied(
    auth_world: World,
) -> None:
    """Only assertions signed with our key are accepted."""
    user = await auth_world.add_user()

    result = await auth_world.auth.handle_token_hook.execute(
        hook_payload(user.id, grant_types=[JWT_BEARER], assertion="not.a.jwt")
    )

    assert result.action == "deny"


async def test_connector_tokens_get_connector_claims(auth_world: World) -> None:
    """MCP-5: the hook checks the connector at every refresh."""
    user = await auth_world.add_user()
    connector = auth_world.add_connector(
        user, expires_at=auth_world.clock.now().replace(year=2027)
    )
    payload = hook_payload(user.id, {"connector_id": str(connector.id), "amr": ["pwd"]})

    result = await auth_world.auth.handle_token_hook.execute(payload)

    assert result.session is not None
    claims = result.session["access_token"]
    assert claims["sid"] == claims["connector_id"] == str(connector.id)
    assert claims["server"] == "student"


async def test_revoked_connector_cannot_refresh(auth_world: World) -> None:
    """UF-MCP-04: revocation stops OAuth refresh tokens."""
    user = await auth_world.add_user()
    connector = auth_world.add_connector(user, revoked_at=auth_world.clock.now())

    result = await auth_world.auth.handle_token_hook.execute(
        hook_payload(user.id, {"connector_id": str(connector.id)})
    )

    assert result.action == "deny"


async def test_connector_of_a_user_who_lost_the_role_is_denied(
    auth_world: World,
) -> None:
    """MCP-5: the role is checked when tokens are refreshed."""
    teacher = await auth_world.add_user(roles={Role.TEACHER})
    connector = auth_world.add_connector(
        teacher, server="admin", scopes=["people:read"]
    )

    result = await auth_world.auth.handle_token_hook.execute(
        hook_payload(teacher.id, {"connector_id": str(connector.id)})
    )

    assert result.action == "deny"
