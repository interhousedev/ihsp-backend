"""Progressive disclosure of tools: a small `tools/list` and four meta tools.

A role server registers dozens of tools; sending every schema to the client costs
context on each conversation. The server therefore lists only the meta tools
(`search_tools`, `describe_tool`, `run_read_tool`, `run_write_tool`) and a short
pinned set. Every other tool stays registered and callable by its own name; the meta
tools find it, describe it and call it through the same guarded function, so scope,
roles, limits, consent, idempotency and the call log all apply under the real name.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from app.interfaces.mcp.auth import IhspAccessToken
from app.interfaces.mcp.constants import ALLOWED_ROLES_BY_SERVER, SourceServerName

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import Tool as RegisteredTool
from mcp.types import Tool, ToolAnnotations
from pydantic import Field

SEARCH_TOOLS = "search_tools"
DESCRIBE_TOOL = "describe_tool"
RUN_READ_TOOL = "run_read_tool"
RUN_WRITE_TOOL = "run_write_tool"
META_TOOLS = frozenset({SEARCH_TOOLS, DESCRIBE_TOOL, RUN_READ_TOOL, RUN_WRITE_TOOL})

FILE_PARAMS_META = "openai/fileParams"
MAX_PINNED = 7  # explicit pins per server; a caller sees only those its roles allow
DEFAULT_HITS = 10
MAX_HITS = 30
_SUMMARY_CHARS = 160
_NAME_WEIGHT = 3
_WORDS = re.compile(r"\w+")


class CatalogMcp(FastMCP):
    """FastMCP whose `tools/list` shows only the meta and pinned tools of the caller.

    Hidden tools stay registered, so a client that cached one can still call it.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Start without tools; `enable_catalog` fills the maps below."""
        super().__init__(*args, **kwargs)
        self.tool_sources: dict[str, SourceServerName] = {}
        self.pinned: frozenset[str] = frozenset()

    def allowed(self, name: str) -> bool:
        """True when a caller's roles allow the source server of tool `name`."""
        source = self.tool_sources.get(name)
        if source is None:
            return False
        token = get_access_token()
        if not isinstance(token, IhspAccessToken):
            return False
        return bool(token.actor.roles & ALLOWED_ROLES_BY_SERVER[source])

    def visible(self) -> list[RegisteredTool]:
        """The registered tools the caller's roles allow (meta tools excluded)."""
        return [
            tool
            for tool in self._tool_manager.list_tools()
            if tool.name in self.tool_sources and self.allowed(tool.name)
        ]

    async def list_tools(self) -> list[Tool]:
        """The meta tools and the pinned tools the caller's roles allow."""
        tools = await super().list_tools()
        if not isinstance(get_access_token(), IhspAccessToken):
            return []
        return [
            tool
            for tool in tools
            if tool.name in META_TOOLS
            or (tool.name in self.pinned and self.allowed(tool.name))
        ]


def enable_catalog(
    mcp: CatalogMcp,
    sources: Mapping[str, SourceServerName],
    pinned: Sequence[str],
) -> None:
    """Record each tool's source server, pin tools and register the meta tools.

    Pinned are `pinned` and every tool with `openai/fileParams` meta: ChatGPT attaches
    a file only to a tool it lists directly, so an upload tool cannot stay hidden.
    """
    if len(pinned) > MAX_PINNED:
        raise ValueError(f"at most {MAX_PINNED} pinned tools, got {len(pinned)}")
    unknown = [name for name in pinned if name not in sources]
    if unknown:
        raise ValueError(f"pinned tools are not registered: {unknown}")
    mcp.tool_sources.update(sources)
    uploads = {
        name
        for name in sources
        if (tool := mcp._tool_manager.get_tool(name)) is not None
        and tool.meta is not None
        and FILE_PARAMS_META in tool.meta
    }
    mcp.pinned = frozenset(pinned) | uploads
    _register_meta_tools(mcp)


def _summary(tool: RegisteredTool) -> str:
    """The first line of the description, clipped."""
    text = (tool.description or "").strip().splitlines()
    line = text[0].strip() if text else ""
    if len(line) > _SUMMARY_CHARS:
        line = line[: _SUMMARY_CHARS - 1].rstrip() + "…"
    return line


def _read_only(tool: RegisteredTool) -> bool:
    """The tool's `readOnlyHint`."""
    return bool(tool.annotations is not None and tool.annotations.readOnlyHint)


def _score(tool: RegisteredTool, words: Sequence[str]) -> int:
    """Keyword score: a hit in the name weighs more than one in the description."""
    name = tool.name.lower()
    description = (tool.description or "").lower()
    return sum(
        (_NAME_WEIGHT if word in name else 0) + (1 if word in description else 0)
        for word in words
    )


def rank(tools: Sequence[RegisteredTool], query: str, limit: int) -> list[Any]:
    """Tools that match `query`, best first (ties by name), at most `limit`."""
    words = _WORDS.findall(query.lower())
    scored = [(_score(tool, words), tool) for tool in tools]
    hits = sorted(
        (item for item in scored if item[0] > 0), key=lambda i: (-i[0], i[1].name)
    )
    return [
        {
            "name": tool.name,
            "summary": _summary(tool),
            "read_only": _read_only(tool),
        }
        for _, tool in hits[:limit]
    ]


def _find(mcp: CatalogMcp, name: str) -> RegisteredTool:
    """A registered tool the caller may see, or a tool error."""
    tool = mcp._tool_manager.get_tool(name)
    if tool is None or name in META_TOOLS or not mcp.allowed(name):
        raise ToolError(f"Unknown tool: {name}. Use search_tools to find one.")
    return tool


async def _run(mcp: CatalogMcp, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call the registered (guarded) tool under its own name."""
    _find(mcp, name)
    result: dict[str, Any] = await mcp._tool_manager.call_tool(name, arguments)
    return result


NameParam = Annotated[
    str, Field(min_length=1, max_length=100, description="Exact tool name.")
]
ArgumentsParam = Annotated[
    dict[str, Any],
    Field(description="Arguments of the tool, as described by describe_tool."),
]


def _register_meta_tools(mcp: CatalogMcp) -> None:
    """Add the four meta tools to the server."""
    reading = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @mcp.tool(name=SEARCH_TOOLS, annotations=reading)
    async def search_tools(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Keywords of what you want to do, in English.",
            ),
        ],
        limit: Annotated[int, Field(ge=1, le=MAX_HITS)] = DEFAULT_HITS,
    ) -> dict[str, Any]:
        """Find tools of this server by keyword (names and descriptions).

        Returns name, a one-line summary and read_only for each match. Next call
        describe_tool for the arguments, then run_read_tool or run_write_tool.
        """
        return {"items": rank(mcp.visible(), query, limit)}

    @mcp.tool(name=DESCRIBE_TOOL, annotations=reading)
    async def describe_tool(name: NameParam) -> dict[str, Any]:
        """Full description, input JSON schema and annotations of one tool."""
        tool = _find(mcp, name)
        annotations = tool.annotations
        return {
            "name": tool.name,
            "description": tool.description,
            "read_only": _read_only(tool),
            "input_schema": tool.parameters,
            "annotations": (
                annotations.model_dump(exclude_none=True) if annotations else {}
            ),
        }

    @mcp.tool(name=RUN_READ_TOOL, annotations=reading)
    async def run_read_tool(
        name: NameParam, arguments: ArgumentsParam
    ) -> dict[str, Any]:
        """Run a read-only tool by name; a tool that can change data is refused.

        Find the name with search_tools and the arguments with describe_tool.
        """
        if not _read_only(_find(mcp, name)):
            raise ToolError(f"{name} changes data: call it with run_write_tool.")
        return await _run(mcp, name, arguments)

    @mcp.tool(
        name=RUN_WRITE_TOOL,
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def run_write_tool(
        name: NameParam, arguments: ArgumentsParam
    ) -> dict[str, Any]:
        """Run a tool that creates, changes or deletes data (it may be destructive).

        ChatGPT must confirm with the user before every call. Find the name with
        search_tools and the arguments with describe_tool.
        """
        return await _run(mcp, name, arguments)
