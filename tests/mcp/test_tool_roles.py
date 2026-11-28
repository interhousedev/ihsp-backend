"""Per-tool roles (`ToolKit.tool(roles=...)`) and the per-source legal consent."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

from app.interfaces.mcp import catalog as catalog_module
from app.interfaces.mcp.auth import IhspAccessToken
from app.interfaces.mcp.catalog import CatalogMcp
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.guard import ToolGuard, ToolRule
from app.shared.actor import Actor, Role
from app.shared.mcp_scopes import ADMISSION_STAFF_ROLES

import pytest


class _Consent:
    """Records the apps asked for; refuses the admission app."""

    def __init__(self) -> None:
        self.apps: list[str | None] = []

    async def execute(
        self, user_id: Any, app: str | None = None
    ) -> None:  # noqa: ANN401
        self.apps.append(app)
        if app == "admission":
            raise LookupError("admission documents not accepted")


class _Limiter:
    async def hit(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        return None


def _actor(*roles: Role) -> Actor:
    return Actor(user_id=uuid4(), roles=frozenset(roles))


def _guard(server: Any, mounted_on: Any = None, consent: Any = None) -> ToolGuard:
    deps = SimpleNamespace(maintenance=None, rate_limiter=_Limiter(), consent=consent)
    return ToolGuard(cast(McpDeps, deps), server, mounted_on=mounted_on)


def test_a_tool_with_roles_is_refused_for_other_roles() -> None:
    staff_only = ToolRule("caseload:read", roles=ADMISSION_STAFF_ROLES)
    for guard in (_guard("admission"), _guard("admission", mounted_on="app")):
        assert guard._role_refused(_actor(Role.STUDENT), staff_only)
        assert not guard._role_refused(_actor(Role.COUNSELOR), staff_only)
        assert not guard._role_refused(_actor(Role.STUDENT), ToolRule("plans:read"))


def test_a_tool_with_roles_is_hidden_from_other_roles_on_a_catalog() -> None:
    mcp = CatalogMcp("t")
    mcp.tool_sources.update(
        {"admission_list_caseload": "admission", "admission_get_today": "admission"}
    )
    mcp.tool_roles["admission_list_caseload"] = ADMISSION_STAFF_ROLES

    def token(*roles: Role) -> IhspAccessToken:
        return cast(IhspAccessToken, SimpleNamespace(actor=_actor(*roles)))

    with (
        patch.object(catalog_module, "get_access_token", lambda: token(Role.STUDENT)),
        patch.object(catalog_module, "IhspAccessToken", SimpleNamespace),
    ):
        assert not mcp.allowed("admission_list_caseload")
        assert mcp.allowed("admission_get_today")
    with (
        patch.object(catalog_module, "get_access_token", lambda: token(Role.MENTOR)),
        patch.object(catalog_module, "IhspAccessToken", SimpleNamespace),
    ):
        assert mcp.allowed("admission_list_caseload")


@pytest.mark.parametrize("mounted_on", [None, "app"])
async def test_admission_tools_require_the_admission_legal_documents(
    mounted_on: Any,  # noqa: ANN401
) -> None:
    consent = _Consent()
    guard = _guard("admission", mounted_on=mounted_on, consent=consent)

    with pytest.raises(LookupError):
        await guard._enforce(_actor(Role.STUDENT), "get_today", ToolRule("x"))
    assert consent.apps == [None, "admission"]


async def test_other_sources_ask_only_the_global_documents() -> None:
    consent = _Consent()
    guard = _guard("teacher", mounted_on="app", consent=consent)
    guard._ai_access = _noop  # type: ignore[method-assign]
    guard.has_scope = _yes  # type: ignore[method-assign]

    await guard._enforce(_actor(Role.TEACHER), "teacher_x", ToolRule("x"))
    assert consent.apps == [None]


async def _noop(*args: Any) -> None:  # noqa: ANN401
    return None


async def _yes(*args: Any) -> bool:  # noqa: ANN401
    return True
