"""Role-filtered admission scopes in the MCP setup and the consent step."""

from uuid import uuid4

from app.modules.identity.application.consent_support import requested_scopes
from app.modules.identity.application.get_mcp_setup import GetMcpSetup, McpEndpoints
from app.modules.identity.domain.errors import RoleMissingError
from app.modules.identity.ports.hydra_gateway import ConsentRequest
from app.shared.actor import Actor, Role

import pytest

STAFF = {"caseload:read", "students:read", "students:write", "documents:review"}
setup = GetMcpSetup(
    McpEndpoints(
        issuer="https://auth.example",
        api_url="https://api.example",
        mcp_base="https://api.example/mcp",
    )
)


def _actor(role: Role) -> Actor:
    return Actor(user_id=uuid4(), roles=frozenset({role}))


def test_setup_scopes_differ_for_applicant_and_counselor() -> None:
    student = setup.execute(_actor(Role.STUDENT), "custom", "admission")
    counselor = setup.execute(_actor(Role.COUNSELOR), "custom", "admission")

    assert student.oauth is not None and counselor.oauth is not None
    assert not set(student.oauth.scopes) & STAFF
    assert "application:read" in student.oauth.scopes
    assert STAFF <= set(counselor.oauth.scopes)
    assert "application:read" not in counselor.oauth.scopes


def test_setup_refuses_a_teacher() -> None:
    with pytest.raises(RoleMissingError):
        setup.execute(_actor(Role.TEACHER), "custom", "admission")


def test_consent_offers_only_the_roles_scopes() -> None:
    request = ConsentRequest.__new__(ConsentRequest)
    object.__setattr__(request, "requested_scope", [])
    student = requested_scopes(request, "admission", frozenset({Role.STUDENT}))
    counselor = requested_scopes(request, "admission", frozenset({Role.COUNSELOR}))

    assert not set(student) & STAFF
    assert set(counselor) == STAFF | {"catalog:read"}
