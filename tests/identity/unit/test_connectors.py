"""ID-27, MCP-2, MCP-4: issuing, listing and revoking MCP connectors."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from app.modules.identity.application.create_connector import NewConnector
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    ConnectorInvalidError,
    RoleMissingError,
    SecondFactorRequiredError,
)
from app.modules.identity.domain.user import User
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError
from app.shared.ids import hash_token, new_id
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


def actor_of(user_id: UUID, *roles: Role) -> Actor:
    """The caller."""
    return Actor(user_id=user_id, roles=frozenset(roles or {Role.STUDENT}))


async def create(world: World, user: User, **overrides: Any) -> NewConnector:
    """Create a connector with sensible defaults."""
    args = {
        "server": "student",
        "name": "Claude - study planner",
        "scopes": ["schedule:read", "homework:read"],
        "course_ids": None,
        "expires_in_days": 90,
        "otp_code": None,
        "ctx": CTX,
    }
    args.update(overrides)
    return await world.auth.create_connector.execute(
        actor_of(user.id, *user.roles), **args
    )


async def test_token_is_shown_once_and_only_its_hash_is_stored(
    auth_world: World,
) -> None:
    """MCP-2: ihsp_mcp_ token of 256 random bits, stored hashed."""
    user = await auth_world.add_user()

    created = await create(auth_world, user)

    assert created.token.startswith("ihsp_mcp_")
    assert len(created.token) == len("ihsp_mcp_") + 43
    stored = auth_world.store.connectors[created.connector.id]
    assert stored.token_hash == hash_token(created.token)
    assert stored.token_prefix == created.token[len("ihsp_mcp_") :][:8]
    assert created.token not in repr(stored)
    assert stored.expires_at == auth_world.clock.now() + timedelta(days=90)
    assert "connector.created" in auth_world.store.audit_types(user.id)


async def test_each_token_is_different(auth_world: World) -> None:
    """MCP-2: random tokens."""
    user = await auth_world.add_user()

    first = await create(auth_world, user)
    second = await create(auth_world, user)

    assert first.token != second.token


async def test_student_cannot_create_an_administration_connector(
    auth_world: World,
) -> None:
    """MCP-1: only servers allowed for the roles."""
    user = await auth_world.add_user()

    with pytest.raises(RoleMissingError):
        await create(
            auth_world, user, server="admin", scopes=["people:read"], expires_in_days=30
        )


async def test_administration_connector_needs_the_step_up_code_and_30_days_at_most(
    auth_world: World,
) -> None:
    """MCP-2: Administration connectors last at most 30 days after an OTP check."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    fields = {"server": "admin", "scopes": ["people:read"], "expires_in_days": 30}

    with pytest.raises(SecondFactorRequiredError):
        await create(auth_world, admin, **fields)
    with pytest.raises(ConnectorInvalidError):
        await create(auth_world, admin, **{**fields, "expires_in_days": 90})

    await auth_world.auth.step_up.execute(actor_of(admin.id, Role.ADMIN), CTX)
    code = auth_world.otp.last("step-up").code
    created = await create(auth_world, admin, **fields, otp_code=code)
    assert created.connector.server == "admin"
    assert created.connector.expires_at == auth_world.clock.now() + timedelta(days=30)


@pytest.mark.parametrize(
    "overrides",
    [
        {"scopes": ["marks:read", "no-such-scope"]},
        {"scopes": []},
        {"scopes": ["courses:read"]},  # an LMS scope on the student server
        {"name": "   "},
        {"expires_in_days": 45},
        {"course_ids": [new_id()]},  # only the LMS server takes course ids
    ],
)
async def test_invalid_connector_requests_are_refused(
    auth_world: World, overrides: dict
) -> None:
    """MCP-2: scopes, expiry and course ids are validated per server."""
    user = await auth_world.add_user()

    with pytest.raises(ConnectorInvalidError):
        await create(auth_world, user, **overrides)

    assert auth_world.store.connectors == {}


async def test_lms_connector_can_be_limited_to_courses(auth_world: World) -> None:
    """MCP-2: for LMS the connector may name its courses."""
    teacher = await auth_world.add_user(roles={Role.TEACHER})
    course = new_id()

    created = await create(
        auth_world,
        teacher,
        server="lms",
        scopes=["courses:read", "courses:draft"],
        course_ids=[course],
    )

    assert created.connector.course_ids == [course]


async def test_connector_list_shows_own_connectors_newest_first(
    auth_world: World,
) -> None:
    """MCP-4: name, server, scopes, kind and the token prefix, never the token."""
    user = await auth_world.add_user()
    other = await auth_world.add_user(
        login="other.user", recovery_email="o@example.org"
    )
    first = await create(auth_world, user, name="First")
    second = await create(auth_world, user, name="Second")
    await create(auth_world, other)

    listed = await auth_world.auth.list_connectors.execute(actor_of(user.id))

    assert [c.name for c in listed] == ["Second", "First"]
    assert {c.id for c in listed} == {first.connector.id, second.connector.id}


async def test_revoking_a_connector_stops_it_at_once(auth_world: World) -> None:
    """MCP-4: revocation works immediately and is audited."""
    user = await auth_world.add_user()
    created = await create(auth_world, user)

    await auth_world.auth.revoke_connector.execute(
        actor_of(user.id), created.connector.id, CTX
    )

    assert auth_world.store.connectors[created.connector.id].revoked_at is not None
    assert await auth_world.redis.exists(f"auth:revoked:{created.connector.id}")
    assert "connector.revoked" in auth_world.store.audit_types(user.id)
    from app.shared.base_error import UnauthorizedError

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.connector_verifier.verify_connector(
            created.token, server="student"
        )


async def test_revoking_an_oauth_connector_cuts_its_hydra_tokens(
    auth_world: World,
) -> None:
    """UF-MCP-04: OAuth connectors also lose their consent session in Hydra."""
    user = await auth_world.add_user()
    connector = auth_world.add_connector(user, hydra_client_id="mcp-client")

    await auth_world.auth.revoke_connector.execute(actor_of(user.id), connector.id, CTX)

    assert auth_world.hydra.last("revoke_consent_sessions") == {
        "subject": str(user.id),
        "client_id": "mcp-client",
    }


async def test_cannot_revoke_someone_elses_connector(auth_world: World) -> None:
    """MCP-4: users manage their own connectors only."""
    owner = await auth_world.add_user()
    stranger = await auth_world.add_user(login="x.y", recovery_email="x@example.org")
    connector = auth_world.add_connector(owner)

    with pytest.raises(NotFoundError):
        await auth_world.auth.revoke_connector.execute(
            actor_of(stranger.id), connector.id, CTX
        )


def test_scope_catalog_lists_three_servers_with_presets(auth_world: World) -> None:
    """MCP-8: scopes with their tools and the task presets."""
    catalog = {c.server: c for c in auth_world.auth.get_mcp_scopes.execute()}

    assert set(catalog) == {"student", "lms", "admin"}
    student = {s.scope: s.tools for s in catalog["student"].scopes}
    assert student["marks:read"] == ("get_marks", "get_results")
    assert {p.key for p in catalog["student"].presets} == {
        "study-planner",
        "grades",
        "revision",
    }
    assert catalog["admin"].roles == [Role.ADMIN]
    assert len(catalog["admin"].scopes) == 6
