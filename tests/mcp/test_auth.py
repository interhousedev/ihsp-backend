"""MCP-3, MCP-5: bearer tokens, audiences and roles decide who may connect."""

from typing import cast

from app.interfaces.mcp.auth import IhspAccessToken, IhspTokenVerifier
from app.interfaces.mcp.constants import ServerName
from app.interfaces.mcp.student.server import build_student_server
from app.shared.actor import Role
from app.shared.contracts.auth import (
    AUDIENCE_MCP_ADMIN,
    AUDIENCE_MCP_LMS,
    AUDIENCE_MCP_STUDENT,
    AccessTokenVerifier,
    ConnectorTokenVerifier,
)
from tests.mcp.conftest import World
from tests.mcp.helpers import tool_names

import pytest
from mcp.server.fastmcp.exceptions import ToolError

RESOURCE = "http://testserver/mcp/student"
METADATA = "http://testserver/.well-known/oauth-protected-resource/mcp/student"


async def test_call_without_token_is_401_with_resource_metadata(world: World) -> None:
    """UF-MCP-02: an unauthenticated client is pointed to the metadata."""
    async with world.serve() as server:
        response = await server.raw.post("/mcp/student/", json={})

    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert 'error="invalid_token"' in challenge
    assert f'resource_metadata="{METADATA}"' in challenge


async def test_unknown_token_is_401(world: World) -> None:
    """UF-MCP-03 2a: a token nobody issued is refused."""
    async with world.serve() as server:
        response = await server.raw.post(
            "/mcp/student/", json={}, headers={"authorization": "Bearer nope"}
        )

    assert response.status_code == 401


async def test_connector_token_is_verified_for_the_mounted_server(
    world: World,
) -> None:
    """MCP-3: connector tokens are bound to one server."""
    token, _ = world.connector_token("lms", "courses:read")

    async with world.serve() as server:
        async with server.session("lms", token) as session:
            names = await tool_names(session)
        wrong = await server.raw.post(
            "/mcp/student/", json={}, headers={"authorization": f"Bearer {token}"}
        )

    assert "list_courses" in names
    assert (token, "lms") in world.connector.calls
    assert (token, "student") in world.connector.calls
    assert wrong.status_code == 401


@pytest.mark.parametrize(
    ("server", "audience"),
    [
        ("student", AUDIENCE_MCP_STUDENT),
        ("lms", AUDIENCE_MCP_LMS),
        ("admin", AUDIENCE_MCP_ADMIN),
    ],
)
async def test_oauth_token_is_checked_against_the_audience_of_its_server(
    world: World, server: str, audience: str
) -> None:
    """MCP-3: Hydra access tokens must carry the audience of this server."""
    roles = (Role.ADMIN, Role.TEACHER, Role.STUDENT)
    token, _ = world.oauth_token(audience, roles=roles)

    async with world.serve() as running:
        response = await running.raw.post(
            f"/mcp/{server}/", json={}, headers={"authorization": f"Bearer {token}"}
        )

    assert (token, audience) in world.access.calls
    assert response.status_code != 401


async def test_oauth_token_of_another_server_is_refused(world: World) -> None:
    """MCP-3: a student token does not open the Administration server."""
    token, _ = world.oauth_token(AUDIENCE_MCP_STUDENT, roles=(Role.ADMIN,))

    async with world.serve() as server:
        response = await server.raw.post(
            "/mcp/admin/", json={}, headers={"authorization": f"Bearer {token}"}
        )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("server", "role"),
    [("student", Role.TEACHER), ("admin", Role.STUDENT), ("admin", Role.TEACHER)],
)
async def test_role_no_longer_held_for_the_server_is_refused(
    world: World, server: ServerName, role: Role
) -> None:
    """MCP-5: the role is checked on every call, not only at issue time."""
    token, _ = world.connector_token(server, "people:read", roles=(role,))

    async with world.serve() as running:
        response = await running.raw.post(
            f"/mcp/{server}/", json={}, headers={"authorization": f"Bearer {token}"}
        )

    assert response.status_code == 401


async def test_verified_token_carries_actor_and_scopes(world: World) -> None:
    """The SDK access token keeps the actor for the tools."""
    token, actor = world.connector_token("student", "marks:read", "schedule:read")
    verifier = IhspTokenVerifier(
        server="student",
        resource_url=RESOURCE,
        access=cast(AccessTokenVerifier, world.access),
        connector=cast(ConnectorTokenVerifier, world.connector),
    )

    access = await verifier.verify_token(token)

    assert isinstance(access, IhspAccessToken)
    assert access.actor == actor
    assert access.scopes == ["marks:read", "schedule:read"]
    assert access.resource == RESOURCE
    assert access.subject == str(actor.user_id)
    assert access.token == ""
    assert await verifier.verify_token("ihsp_mcp_unknown") is None


async def test_tool_without_authenticated_actor_is_refused(world: World) -> None:
    """A direct call (no HTTP, no token) never reaches the use cases."""
    server = build_student_server(world.deps())

    with pytest.raises(ToolError, match="Not authenticated"):
        await server.call_tool("get_schedule", {})

    assert world.schedule.calls == []
