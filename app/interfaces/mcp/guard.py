"""Per-call checks of MCP tools: login, rate limit, scope, audit, error mapping, log."""

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, TypeVar, cast

from app.interfaces.mcp.auth import IhspAccessToken
from app.interfaces.mcp.call_log import (
    LogSpec,
    check_log_spec,
    redact_arguments,
    summarize_result,
)
from app.interfaces.mcp.constants import (
    ALLOWED_ROLES_BY_SERVER,
    CALLS_PER_MINUTE,
    SCOPES_BY_SERVER,
    USER_CALLS_PER_MINUTE,
    ServerName,
    ToolLimit,
)
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.errors import (
    McpRateLimitedError,
    McpScopeError,
    McpUnauthenticatedError,
)
from app.interfaces.mcp.jsonable import to_jsonable, to_jsonable_dict
from app.shared.actor import Actor
from app.shared.ai_access import AiScope
from app.shared.base_error import (
    BaseError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)
from app.shared.client_ip import client_address, parse_trusted_proxies
from app.shared.contracts.ai import AiAccessRevokedError
from app.shared.contracts.mcp_calls import McpCallOutcome, McpCallRecord
from app.shared.ids import new_id
from app.shared.lms_scopes import effective_scopes
from app.shared.notifications import AuditDraft
from app.shared.usage_context import bind_usage_actor, reset_usage_actor

import structlog
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.lowlevel.server import request_ctx

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


@dataclass(frozen=True, slots=True)
class ToolRule:
    """What the guard enforces and logs for one tool."""

    scope: str
    read_only: bool = True
    destructive: bool = False
    limit: ToolLimit | None = None
    log: LogSpec | None = None


@dataclass(slots=True)
class _Trace:
    """How a call ended; the default covers a cancelled call."""

    outcome: McpCallOutcome = "error"
    error_code: str | None = None
    error_id: str | None = None
    summary: dict[str, Any] | None = None


class ToolGuard:
    """Runs the checks of MCP-5, MCP-7 and UF-MCP-03 around every tool of a server."""

    def __init__(
        self, deps: McpDeps, server: ServerName, *, mounted_on: ServerName | None = None
    ) -> None:
        """Bind the guard to the dependencies and the server whose tools it guards.

        `mounted_on="app"` makes `server` a source of the universal server: the tool
        names and scopes it sees are prefixed (`teacher_`, `teacher:`), the call log
        says "app", and every call re-checks the roles against the source server.
        """
        self.deps = deps
        self.server = server
        self.public: ServerName = mounted_on or server
        self.composite = mounted_on == "app"
        self.scope_prefix = f"{server}:" if self.composite else ""
        self.name_prefix = f"{server}_" if self.composite else ""
        self.registered: dict[str, ToolRule] = {}
        self._log_writes: set[asyncio.Task[None]] = set()

    def requires_scope(
        self,
        scope: str,
        *,
        limit: ToolLimit | None = None,
        log: LogSpec | None = None,
        read_only: bool = True,
        destructive: bool = False,
    ) -> Callable[[ToolFn], ToolFn]:
        """Decorate a tool so it runs only for tokens granted `scope`."""
        rule = ToolRule(scope, read_only, destructive, limit, log)

        def decorate(fn: ToolFn) -> ToolFn:
            tool = self.name_prefix + getattr(fn, "__name__", "tool")
            check_log_spec(tool, fn, log)
            self.registered[tool] = rule

            @functools.wraps(fn)
            async def wrapper(
                *args: Any, **kwargs: Any
            ) -> dict[str, Any]:  # noqa: ANN401
                return await self._call(fn, tool, rule, args, kwargs)

            return cast(ToolFn, wrapper)

        return decorate

    async def has_scope(self, actor: Actor, scope: str) -> bool:
        """True when the actor holds `scope`, directly or through the OAuth overlay.

        For a second scope inside a tool (`flashcards:delete`, `files:read.all`); the
        actor is the one the tool got from `current_actor()`, scopes un-prefixed.
        """
        if scope in effective_scopes(actor.scopes):
            return True
        return scope in await self._overlay(actor)

    def _view(self, actor: Actor) -> Actor:
        """The actor as the source server's tools see it (scopes un-prefixed).

        The universal server's tokens carry `teacher:marks:write`; the tools and the
        use cases behind them check `marks:write`. Course markers pass through.
        """
        if not self.composite:
            return actor
        prefix = self.scope_prefix
        scopes = frozenset(
            scope.removeprefix(prefix) if scope.startswith(prefix) else scope
            for scope in actor.scopes
            if scope.startswith((prefix, "course:"))
        )
        return replace(actor, scopes=scopes)

    async def charge(self, actor: Actor, limit: ToolLimit) -> None:
        """Count one call of a cost class; for a tool that charges only some calls."""
        try:
            await self.deps.rate_limiter.hit(
                f"mcp:{limit.name}:{actor.user_id}",
                limit=limit.limit,
                window_seconds=limit.window_seconds,
            )
        except RateLimitedError as error:
            raise McpRateLimitedError(params=error.params) from error

    async def _call(
        self,
        fn: Callable[..., ToolResult],
        tool: str,
        rule: ToolRule,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        actor: Actor | None = None
        trace = _Trace()
        started = time.monotonic()
        try:
            token_actor = _token_actor()
            actor = self._view(token_actor)
            await self._enforce(actor, tool, rule)
            if self.server == "admin":
                await self._audit(
                    actor,
                    "mcp.call",
                    tool,
                    {"arguments": clip_for_audit(to_jsonable(kwargs))},
                )
            result = await self._run(fn, actor, tool, args, kwargs)
            trace.outcome = "ok"
            trace.summary = summarize_result(result, rule.log)
            return result
        except ToolError:
            raise
        except BaseError as error:
            trace.outcome = _outcome_of(error)
            trace.error_code = error.code
            raise ToolError(self._message(error)) from error
        except Exception as error:  # noqa: BLE001 - last resort at the interface edge
            trace.error_id = str(new_id())
            raise self._internal(tool, error, trace.error_id) from error
        finally:
            if actor is not None:
                await self._log_call(actor, tool, rule, kwargs, trace, started)

    async def _run(
        self,
        fn: Callable[..., ToolResult],
        actor: Actor,
        tool: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        reset = _ACTOR.set(actor)
        usage = bind_usage_actor(actor)  # AI calls of the tool are for this actor
        try:
            result = await fn(*args, **kwargs)
        except ForbiddenError as error:
            await self._audit_denied(actor, tool, error.code)
            raise
        finally:
            reset_usage_actor(usage)
            _ACTOR.reset(reset)
        return to_jsonable_dict(result)

    async def _enforce(self, actor: Actor, tool: str, rule: ToolRule) -> None:
        try:
            await self._limit(actor)
            if (
                self.composite
                and not actor.roles & ALLOWED_ROLES_BY_SERVER[self.server]
            ):
                raise McpScopeError(params={"scope": self.scope_prefix + rule.scope})
            await self._ai_access(actor)
            if not await self.has_scope(actor, rule.scope):
                raise McpScopeError(params={"scope": self.scope_prefix + rule.scope})
            if rule.limit is not None:  # after the scope: a refusal spends no class
                await self.charge(actor, rule.limit)
        except (RateLimitedError, ForbiddenError) as error:
            await self._audit_denied(
                actor, tool, error.code, scope=self.scope_prefix + rule.scope
            )
            raise

    async def _limit(self, actor: Actor) -> None:
        subject = actor.connector_id or actor.user_id
        try:
            await self.deps.rate_limiter.hit(
                f"mcp:{subject}", limit=CALLS_PER_MINUTE, window_seconds=60
            )
            await self.deps.rate_limiter.hit(
                f"mcp:user:{actor.user_id}",
                limit=USER_CALLS_PER_MINUTE,
                window_seconds=60,
            )
        except RateLimitedError as error:
            raise McpRateLimitedError(params=error.params) from error

    async def _ai_access(self, actor: Actor) -> None:
        """Refuse a user whom Administration revoked the AI from (either scope)."""
        access = await self.deps.limits.ai_access(actor.user_id)
        scopes: tuple[AiScope, ...] = ("chat", "notebooks")
        for scope in scopes:
            if access.blocks(scope):
                raise AiAccessRevokedError(params={"scope": scope})

    async def _overlay(self, actor: Actor) -> frozenset[str]:
        """Scopes granted after an OAuth token was issued; never on Administration."""
        port = self.deps.scope_overlay
        if (
            port is None
            or self.server == "admin"
            or actor.client_id is None
            or actor.connector_id is None
        ):
            return frozenset()
        try:
            extra = await port.extra_scopes(actor.connector_id)
        except Exception:  # noqa: BLE001 - fail closed: the token's own scopes remain
            log.exception("mcp.scope_overlay_failed", server=self.server)
            return frozenset()
        if self.composite:
            extra = frozenset(
                scope.removeprefix(self.scope_prefix)
                for scope in extra
                if scope.startswith(self.scope_prefix)
            )
        return extra & frozenset(SCOPES_BY_SERVER[self.server])

    async def _audit_denied(
        self, actor: Actor, tool: str, reason: str, *, scope: str | None = None
    ) -> None:
        await self._audit(actor, "mcp.denied", tool, {"reason": reason, "scope": scope})

    async def _audit(
        self, actor: Actor, event_type: str, tool: str, extra: dict[str, Any]
    ) -> None:
        connector = str(actor.connector_id) if actor.connector_id else None
        metadata = {
            "server": self.public,
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

    async def _log_call(
        self,
        actor: Actor,
        tool: str,
        rule: ToolRule,
        kwargs: dict[str, Any],
        trace: _Trace,
        started: float,
    ) -> None:
        """Store the trace; a failed write never fails the call (B1)."""
        try:
            entry = McpCallRecord(
                user_id=actor.user_id,
                connector_id=actor.connector_id,
                client_id=actor.client_id,
                server=self.public,
                tool=tool,
                scope=self.scope_prefix + rule.scope,
                read_only=rule.read_only,
                outcome=trace.outcome,
                error_code=trace.error_code,
                error_id=trace.error_id,
                duration_ms=int((time.monotonic() - started) * 1000),
                arguments=redact_arguments(kwargs, rule.log),
                result_summary=trace.summary,
                ip=self._client_ip(),
            )
            write = asyncio.ensure_future(self.deps.call_log.record(entry))
            self._log_writes.add(write)
            write.add_done_callback(self._log_writes.discard)
            await asyncio.shield(write)  # survives a cancelled long-poll
        except Exception:  # noqa: BLE001 - see the docstring
            log.exception("mcp.call_log_failed", tool=tool, server=self.server)

    def _client_ip(self) -> str | None:
        """The client through the trusted proxy rule; None outside an HTTP request."""
        try:
            request = request_ctx.get().request
        except LookupError:
            return None
        if request is None:
            return None
        client = getattr(request, "client", None)
        return client_address(
            client.host if client else None,
            request.headers.get("x-forwarded-for"),
            parse_trusted_proxies(self.deps.settings.http.trusted_proxies),
        )

    def _message(self, error: BaseError) -> str:
        text = self.deps.t(error.message_key, **error.params)
        return error.support_details if text == error.message_key else text

    def _internal(self, tool: str, error: Exception, error_id: str) -> ToolError:
        log.exception(
            "mcp.tool_failed", tool=tool, server=self.server, error_id=error_id
        )
        return ToolError(self.deps.t("mcp-internal-error", error_id=error_id))


def _outcome_of(error: BaseError) -> McpCallOutcome:
    if isinstance(error, RateLimitedError):
        return "rate_limited"
    if isinstance(error, ForbiddenError):
        return "denied"
    if isinstance(error, NotFoundError):
        return "not_found"
    if isinstance(error, ValidationFailedError):
        return "invalid"
    return "error"


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
