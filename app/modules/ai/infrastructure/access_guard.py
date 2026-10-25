"""Refuses the model calls of a user whom Administration revoked the AI from.

It wraps the LLM gateway under the usage ledger, so every path that calls a model
(web chat, notebooks and Studio, the Telegram bot, MCP tools, jobs) passes here. The
user is the one the request, bot update, MCP call or job bound with
`usage_context` (the same user the ledger counts); a call with no user is a system
call and is not restricted. A refused call reaches no provider and costs nothing.
"""

from collections.abc import AsyncIterator
from typing import Any

from app.shared.ai_access import AiScope, scope_of
from app.shared.contracts.ai import AiAccessRevokedError, LlmGateway, LlmTuning
from app.shared.limits import LimitsProvider
from app.shared.usage_context import current_ai_scope, current_usage_actor


class AccessGuardedLlmGateway:
    """Implements `LlmGateway`: checks the revoked scopes, then delegates."""

    def __init__(self, inner: LlmGateway, limits: LimitsProvider) -> None:
        """Keep the gateway to call and the limits provider (cached 30 seconds)."""
        self._inner = inner
        self._limits = limits

    async def _require(self, tuning: LlmTuning | None) -> None:
        user_id = current_usage_actor().user_id
        if user_id is None:
            return
        # A caller that bound its scope (notebook discovery) decides, else the task.
        scope: AiScope = scope_of(tuning.task if tuning is not None else None)
        bound = current_ai_scope()
        if bound == "chat":
            scope = "chat"
        elif bound == "notebooks":
            scope = "notebooks"
        if (await self._limits.ai_access(user_id)).blocks(scope):
            raise AiAccessRevokedError(params={"scope": scope})

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        tuning: LlmTuning | None = None,
    ) -> dict[str, Any]:
        """Refuse a revoked user, else run `complete`."""
        await self._require(tuning)
        return await self._inner.complete(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            provider=provider,
            tuning=tuning,
        )

    async def complete_json(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        tuning: LlmTuning | None = None,
    ) -> dict[str, Any]:
        """Refuse a revoked user, else run `complete_json`."""
        await self._require(tuning)
        return await self._inner.complete_json(
            model=model,
            system=system,
            messages=messages,
            schema_name=schema_name,
            schema=schema,
            max_tokens=max_tokens,
            provider=provider,
            timeout_seconds=timeout_seconds,
            tuning=tuning,
        )

    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        tuning: LlmTuning | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream after the check; the refusal is raised on the first item."""
        return self._streamed(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            provider=provider,
            timeout_seconds=timeout_seconds,
            tuning=tuning,
            tools=tools,
        )

    async def _streamed(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        provider: dict[str, Any] | None,
        timeout_seconds: float | None,
        tuning: LlmTuning | None,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        await self._require(tuning)
        async for item in self._inner.stream(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            provider=provider,
            timeout_seconds=timeout_seconds,
            tuning=tuning,
            tools=tools,
        ):
            yield item
