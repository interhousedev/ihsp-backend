"""What each tool file receives to register itself on a server."""

from collections.abc import Callable
from dataclasses import dataclass

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
        self, scope: str, *, read_only: bool = True, destructive: bool = False
    ) -> Callable[[ToolFn], ToolFn]:
        """Register a tool that needs `scope` (guard first, then the SDK decorator)."""
        register = self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=read_only,
                destructiveHint=destructive,
                idempotentHint=read_only,
                openWorldHint=False,
            )
        )

        def decorate(fn: ToolFn) -> ToolFn:
            guarded = self.guard.requires_scope(scope)(fn)
            register(guarded)
            return guarded

        return decorate
