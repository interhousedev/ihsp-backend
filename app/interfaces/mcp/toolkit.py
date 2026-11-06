"""What each tool file receives to register itself on a server."""

from collections.abc import Callable
from dataclasses import dataclass

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT, ToolLimit
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.guard import ToolFn, ToolGuard

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


@dataclass(frozen=True, slots=True)
class ToolKit:
    """One server, its dependencies and its guard."""

    mcp: FastMCP
    deps: McpDeps
    guard: ToolGuard

    def tool(
        self,
        scope: str,
        *,
        read_only: bool = True,
        destructive: bool = False,
        idempotent: bool | None = None,
        limit: ToolLimit | None = None,
        log: LogSpec | None = None,
    ) -> Callable[[ToolFn], ToolFn]:
        """Register a tool that needs `scope` (guard first, then the SDK decorator).

        `limit` is the cost class, counted per user. Student write tools default to
        WRITE_LIMIT. `log` says what the call log may store: without it, the name only.
        `idempotent` defaults to `read_only`; set False for a read with a side effect.
        """
        register = self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=read_only,
                destructiveHint=destructive,
                idempotentHint=read_only if idempotent is None else idempotent,
                openWorldHint=False,
            )
        )
        if limit is None and not read_only and self.guard.server == "student":
            limit = WRITE_LIMIT

        def decorate(fn: ToolFn) -> ToolFn:
            guarded = self.guard.requires_scope(
                scope,
                limit=limit,
                log=log,
                read_only=read_only,
                destructive=destructive,
            )(fn)
            register(guarded)
            return guarded

        return decorate
