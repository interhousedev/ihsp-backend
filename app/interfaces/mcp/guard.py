"""Per-call checks of MCP tools: login, rate limit, scope, audit, error mapping."""

import functools
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, TypeVar, cast

from app.interfaces.mcp.auth import IhspAccessToken
from app.interfaces.mcp.constants import CALLS_PER_MINUTE, ServerName
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.errors import (
    McpRateLimitedError,
    McpScopeError,
    McpUnauthenticatedError,
)
from app.interfaces.mcp.jsonable import to_jsonable, to_jsonable_dict
from app.shared.actor import Actor
from app.shared.base_error import BaseError, ForbiddenError, RateLimitedError
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft

import structlog
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp.exceptions import ToolError

log = structlog.get_logger(__name__)

ToolResult = Awaitable[dict[str, Any]]
ToolFn = TypeVar("ToolFn", bound=Callable[..., ToolResult])

_ACTOR: ContextVar[Actor | None] = ContextVar("mcp_actor", default=None)

_MAX_AUDIT_TEXT = 200
_MAX_AUDIT_ITEMS = 20


def current_actor() -> Actor:
    """Return the actor of the tool call that is running (set by the guard)."""
    actor = _ACTOR.get()
    if actor is None:
        raise McpUnauthenticatedError()
    return actor


class ToolGuard:
    """Runs the checks of MCP-5, MCP-7 and UF-MCP-03 around every tool of a server."""

    def __init__(self, deps: McpDeps, server: ServerName) -> None:
        """Bind the guard to the dependencies and one server."""
        self.deps = deps
        self.server = server

    def requires_scope(self, scope: str) -> Callable[[ToolFn], ToolFn]:
        """Decorate a tool so it runs only for tokens granted `scope`."""

        def decorate(fn: ToolFn) -> ToolFn:
            tool = getattr(fn, "__name__", "tool")

            @functools.wraps(fn)
            async def wrapper(
                *args: Any, **kwargs: Any
            ) -> dict[str, Any]:  # noqa: ANN401
                return await self._call(fn, tool, scope, args, kwargs)

            return cast(ToolFn, wrapper)

        return decorate

    async def _call(
        self,
        fn: Callable[..., ToolResult],
        tool: str,
        scope: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            actor = _token_actor()
            await self._enforce(actor, tool, scope)
            if self.server == "admin":
                await self._audit(
                    actor,
                    "mcp.call",
                    tool,
                    {"arguments": clip_for_audit(to_jsonable(kwargs))},
                )
            return await self._run(fn, actor, tool, args, kwargs)
        except ToolError:
            raise
        except BaseError as error:
            raise ToolError(self._message(error)) from error
        except Exception as error:  # noqa: BLE001 - last resort at the interface edge
            raise self._internal(tool, error) from error

    async def _run(
        self,
        fn: Callable[..., ToolResult],
        actor: Actor,
        tool: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        reset = _ACTOR.set(actor)
        try:
            result = await fn(*args, **kwargs)
        except ForbiddenError as error:
            await self._audit_denied(actor, tool, error.code)
            raise
        finally:
            _ACTOR.reset(reset)
        return to_jsonable_dict(result)

    async def _enforce(self, actor: Actor, tool: str, scope: str) -> None:
        try:
            await self._limit(actor)
            if scope not in actor.scopes:
                raise McpScopeError(params={"scope": scope})
        except (RateLimitedError, ForbiddenError) as error:
            await self._audit_denied(actor, tool, error.code, scope=scope)
            raise

    async def _limit(self, actor: Actor) -> None:
        subject = actor.connector_id or actor.user_id
        try:
            await self.deps.rate_limiter.hit(
                f"mcp:{subject}", limit=CALLS_PER_MINUTE, window_seconds=60
            )
        except RateLimitedError as error:
            raise McpRateLimitedError(params=error.params) from error

    async def _audit_denied(
        self, actor: Actor, tool: str, reason: str, *, scope: str | None = None
    ) -> None:
        await self._audit(actor, "mcp.denied", tool, {"reason": reason, "scope": scope})

    async def _audit(
        self, actor: Actor, event_type: str, tool: str, extra: dict[str, Any]
    ) -> None:
        connector = str(actor.connector_id) if actor.connector_id else None
        metadata = {
            "server": self.server,
            "tool": tool,
            "connector_id": connector,
            **extra,
        }
        await self.deps.audit.audit(
            AuditDraft(
                type=event_type,
                user_id=actor.user_id,
                actor_id=actor.user_id,
                metadata=metadata,
            )
        )

    def _message(self, error: BaseError) -> str:
        text = self.deps.t(error.message_key, **error.params)
        return error.support_details if text == error.message_key else text

    def _internal(self, tool: str, error: Exception) -> ToolError:
        error_id = str(new_id())
        log.exception(
            "mcp.tool_failed", tool=tool, server=self.server, error_id=error_id
        )
        return ToolError(self.deps.t("mcp-internal-error", error_id=error_id))


def _token_actor() -> Actor:
    token = get_access_token()
    if not isinstance(token, IhspAccessToken):
        raise McpUnauthenticatedError()
    return token.actor


def clip_for_audit(value: Any) -> Any:  # noqa: ANN401 - JSON value of any shape
    """Shorten long strings and lists so audit rows stay small."""
    if isinstance(value, str):
        return value[:_MAX_AUDIT_TEXT]
    if isinstance(value, dict):
        return {key: clip_for_audit(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clip_for_audit(item) for item in value[:_MAX_AUDIT_ITEMS]]
    return value
