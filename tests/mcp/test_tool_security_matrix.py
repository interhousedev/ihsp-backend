"""MCP-5, MCP-7, B1: rules every tool obeys; a new tool joins this suite by existing."""

import json
from types import ModuleType, SimpleNamespace
from typing import Any, cast

from app.interfaces.mcp.admin.server import TOOL_MODULES as ADMIN_MODULES
from app.interfaces.mcp.constants import (
    SCOPES_BY_SERVER,
    SERVERS,
    WRITE_LIMIT,
    ServerName,
)
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.factory import make_toolkit
from app.interfaces.mcp.guard import ToolRule
from app.interfaces.mcp.lms.server import TOOL_MODULES as LMS_MODULES
from app.interfaces.mcp.student.server import TOOL_MODULES as STUDENT_MODULES
from app.settings import Settings
from app.shared.ai_access import AiAccess
from app.shared.mcp_scopes import READ_ONLY_TOOLS_IN_WRITE_SCOPES, scope_info
from tests.mcp.conftest import World
from tests.mcp.helpers import call, text_of

import pytest
from mcp.types import Tool

MODULES: dict[ServerName, tuple[ModuleType, ...]] = {
    "student": STUDENT_MODULES,
    "lms": LMS_MODULES,
    "admin": ADMIN_MODULES,
}
CANARY = "CANARY-text-from-the-client"
ACTOR_PARAMETERS = {"user_id", "owner_id", "student_id", "actor_id", "issued_to"}
ID = "00000000-0000-0000-0000-000000000001"


def _rules(server: ServerName, deps: Any) -> dict[str, ToolRule]:
    kit = make_toolkit(deps, server, title="t", instructions_key="mcp-internal-error")
    for module in MODULES[server]:
        module.register(kit)
    return kit.guard.registered


def _live_tools() -> list[tuple[ServerName, str]]:
    """Tools really registered (collected before any fixture exists)."""
    deps = SimpleNamespace(
        settings=Settings(),
        t=lambda key, **params: key,
        access_verifier=None,
        connector_verifier=None,
    )
    return [
        (server, name)
        for server in SERVERS
        for name in _rules(server, cast(McpDeps, deps))
    ]


ALL_TOOLS = _live_tools()
IDS = [f"{server}-{tool}" for server, tool in ALL_TOOLS]


def _value(schema: dict[str, Any], defs: dict[str, Any]) -> Any:  # noqa: C901
    """A minimal valid value of a JSON schema; strings carry the canary."""
    if "$ref" in schema:
        return _value(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for union in ("anyOf", "oneOf"):
        if union in schema:
            real = [s for s in schema[union] if s.get("type") != "null"]
            return _value(real[0], defs)
    kind = schema.get("type")
    if kind == "string":
        return _string(schema)
    if kind in ("integer", "number"):
        return schema.get("minimum", schema.get("exclusiveMinimum", 0) + 1)
    if kind == "boolean":
        return True
    if kind == "array":
        return [_value(schema.get("items", {}), defs)]
    if kind == "object":
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        return {name: _value(properties[name], defs) for name in required}
    return CANARY


def _string(schema: dict[str, Any]) -> str:
    if schema.get("format") == "uuid":
        return ID
    if schema.get("format") == "date":
        return "2026-10-07"
    if schema.get("format") == "date-time":
        return "2026-10-07T00:00:00Z"
    if "pattern" in schema:
        return "a"
    limit = schema.get("maxLength")
    return CANARY[:limit] if limit else CANARY


def _arguments(tool: Tool) -> dict[str, Any]:
    schema = tool.inputSchema
    properties = schema.get("properties", {})
    defs = schema.get("$defs", {})
    required = set(schema.get("required", []))
    # Optional free text too, so the log sees it; other optional shapes are left out.
    return {
        name: _value(prop, defs)
        for name, prop in properties.items()
        if name in required or _is_plain_text(prop)
    }


def _is_plain_text(schema: dict[str, Any]) -> bool:
    options = schema.get("anyOf", [schema])
    return any(
        option.get("type") == "string"
        and not {"format", "pattern", "enum"} & set(option)
        for option in options
    )


async def _tool(world: World, server: ServerName, name: str, token: str) -> Tool:
    async with world.serve() as running:
        async with running.session(server, token) as session:
            listed = await session.list_tools()
    return next(tool for tool in listed.tools if tool.name == name)


@pytest.mark.parametrize(("server", "name"), ALL_TOOLS, ids=IDS)
async def test_a_token_without_the_scope_is_refused_and_audited(
    world: World, server: ServerName, name: str
) -> None:
    """MCP-5, MCP-7: every other scope is not enough."""
    rule = _rules(server, world.deps())[name]
    others = [s for s in SCOPES_BY_SERVER[server] if s != rule.scope]
    token, _ = world.connector_token(server, *others)
    tool = await _tool(world, server, name, token)

    async with world.session(server, token) as session:
        result = await call(session, name, **_arguments(tool))

    assert result.isError
    assert "insufficient_scope" in text_of(result)
    [event] = world.audit.of_type("mcp.denied")
    assert event.metadata is not None and event.metadata["tool"] == name


@pytest.mark.parametrize(("server", "name"), ALL_TOOLS, ids=IDS)
async def test_a_user_with_ai_access_revoked_is_refused(
    world: World, server: ServerName, name: str
) -> None:
    """Security: revoked AI access stops every MCP path."""
    token, actor = world.connector_token(server, *SCOPES_BY_SERVER[server])
    tool = await _tool(world, server, name, token)
    world.revoked_ai[actor.user_id] = AiAccess(chat_blocked=True)

    async with world.session(server, token) as session:
        result = await call(session, name, **_arguments(tool))

    assert result.isError
    assert world.call_log.records[-1].outcome == "denied"


@pytest.mark.parametrize(("server", "name"), ALL_TOOLS, ids=IDS)
async def test_client_text_never_reaches_the_call_log(
    world: World, server: ServerName, name: str
) -> None:
    """B1: whatever a tool does, its free text is not stored."""
    token, _ = world.connector_token(server, *SCOPES_BY_SERVER[server])
    tool = await _tool(world, server, name, token)

    async with world.session(server, token) as session:
        await call(session, name, **_arguments(tool))

    [row] = world.call_log.records
    assert row.tool == name
    stored = json.dumps([row.arguments, row.result_summary])
    assert CANARY[:6] not in stored


@pytest.mark.parametrize(("server", "name"), ALL_TOOLS, ids=IDS)
def test_tool_is_registered_with_a_scope_of_its_server_and_explicit_rules(
    world: World, server: ServerName, name: str
) -> None:
    """MCP-8, B1: a write tool has an explicit LogSpec and the write hints."""
    rule = _rules(server, world.deps())[name]
    info = scope_info(server, rule.scope)

    assert name in info.tools
    if info.write and name not in READ_ONLY_TOOLS_IN_WRITE_SCOPES:
        assert rule.read_only is False
        assert rule.log is not None, f"{name} needs an explicit LogSpec"
    else:
        assert rule.read_only is True
    if name.startswith("delete_"):
        assert rule.destructive is True


@pytest.mark.parametrize(("server", "name"), ALL_TOOLS, ids=IDS)
def test_write_tools_of_the_student_server_have_the_write_limit(
    world: World, server: ServerName, name: str
) -> None:
    """Limit class: writes cost more unless a tool declares its own class."""
    rule = _rules(server, world.deps())[name]

    if server == "student" and not rule.read_only:
        assert rule.limit is not None
        assert rule.limit.limit <= WRITE_LIMIT.limit


@pytest.mark.parametrize("server", ["student"])
async def test_no_student_tool_takes_a_user_from_its_arguments(
    world: World, server: ServerName
) -> None:
    """Per-tool rule 1: the actor comes from the guard only."""
    token, _ = world.connector_token(server, *SCOPES_BY_SERVER[server])

    async with world.session(server, token) as session:
        listed = await session.list_tools()

    for tool in listed.tools:
        assert not ACTOR_PARAMETERS & set(
            tool.inputSchema.get("properties", {})
        ), tool.name
