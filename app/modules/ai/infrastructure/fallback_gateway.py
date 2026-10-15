"""Fails over between two LLM providers (OpenRouter and the Anthropic API).

Two orders, one class (`IHSP_ANTHROPIC__MODE`):

- `fallback` (default): OpenRouter is the primary; a limit failure (402, a 429 left
  after OpenRouter's own retry, or a key or credit limit message) of a mapped model
  (Claude Haiku 5.5) is retried on Anthropic with the mapped model id.
- `default`: a mapped model goes to Anthropic first; a rate limit, an overload (529)
  or a 5xx falls back to OpenRouter with the model id it had. Unmapped models always
  go to OpenRouter.

Which failures switch, and which model id each side gets, is passed in; every other
error propagates unchanged. A stream switches only before its first delta. The
answer's usage names the model and provider that ran (`model`, `provider`), so the
usage ledger records the call that answered.
"""

from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, Final

from app.modules.ai.domain.errors import AiProviderError
from app.shared.contracts.ai import LlmGateway, LlmTuning

import structlog

log = structlog.get_logger(__name__)

LIMIT_STATUSES: Final = frozenset({402, 429})
OVERLOAD_STATUSES: Final = frozenset({429, 529})
LIMIT_PHRASES: Final = (
    "insufficient credits",
    "credit limit",
    "key limit",
    "limit exceeded",
    "more credits",
)

ModelRoute = Callable[[str], str | None]
"""Caller's model id -> this side's model id; None = this side does not take it."""
SwitchRule = Callable[[BaseException], bool]


def is_limit_error(exc: BaseException) -> bool:
    """True when OpenRouter refused for credit, key limit or rate limit."""
    if not isinstance(exc, AiProviderError):
        return False
    if exc.params.get("status") in LIMIT_STATUSES:
        return True
    details = exc.support_details.lower()
    return any(phrase in details for phrase in LIMIT_PHRASES)


def is_overload_error(exc: BaseException) -> bool:
    """True when the Anthropic API is rate limited, overloaded or failing (5xx)."""
    if not isinstance(exc, AiProviderError):
        return False
    status = exc.params.get("status")
    if not isinstance(status, int):
        return False
    return status in OVERLOAD_STATUSES or status >= 500


def never(_: BaseException) -> bool:
    """A switch rule that never switches (the failover is off)."""
    return False


def same_model(model: str) -> str:
    """The route of a provider that takes every model under the caller's id."""
    return model


def mapped_models(models: Mapping[str, str]) -> ModelRoute:
    """The route of the models in `models` (caller id -> this side's id)."""
    table = dict(models)
    return lambda model: table.get(model)


class FallbackLlmGateway:
    """Implements `LlmGateway`: `primary`, then `secondary` after a switch failure.

    `primary_route` None-maps a model to skip the primary (it goes straight to the
    secondary); `secondary_route` None-maps a model to a secondary that does not take
    it, so its failures propagate.
    """

    def __init__(
        self,
        primary: LlmGateway,
        secondary: LlmGateway,
        *,
        primary_route: ModelRoute,
        secondary_route: ModelRoute,
        switch_on: SwitchRule,
    ) -> None:
        """Wire the two providers, their model routes and the switch rule."""
        self.first = primary
        self.second = secondary
        self._primary_route = primary_route
        self._secondary_route = secondary_route
        self._switch_on = switch_on

    def _switch(self, model: str, exc: BaseException) -> str | None:
        target = self._secondary_route(model)
        if target is None or not self._switch_on(exc):
            return None
        log.warning("ai.failover", model=model, target=target)
        return target

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
        """`complete` on the primary, on the secondary after a switch failure."""
        args: dict[str, Any] = {
            "system": system,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
            "provider": provider,
            "tuning": tuning,
        }
        first = self._primary_route(model)
        if first is None:
            return await self.second.complete(
                model=self._secondary_route(model) or model, **args
            )
        try:
            return await self.first.complete(model=first, **args)
        except AiProviderError as exc:
            target = self._switch(model, exc)
            if target is None:
                raise
        return await self.second.complete(model=target, **args)

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
        """`complete_json` on the primary, on the secondary after a switch failure."""
        args: dict[str, Any] = {
            "system": system,
            "messages": messages,
            "schema_name": schema_name,
            "schema": schema,
            "max_tokens": max_tokens,
            "provider": provider,
            "timeout_seconds": timeout_seconds,
            "tuning": tuning,
        }
        first = self._primary_route(model)
        if first is None:
            return await self.second.complete_json(
                model=self._secondary_route(model) or model, **args
            )
        try:
            return await self.first.complete_json(model=first, **args)
        except AiProviderError as exc:
            target = self._switch(model, exc)
            if target is None:
                raise
        return await self.second.complete_json(model=target, **args)

    async def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        tuning: LlmTuning | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream from the primary; a switch failure before any delta moves on."""
        args: dict[str, Any] = {
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
            "provider": provider,
            "timeout_seconds": timeout_seconds,
            "tuning": tuning,
        }
        first = self._primary_route(model)
        if first is None:
            direct = self._secondary_route(model) or model
            async for item in self.second.stream(model=direct, **args):
                yield item
            return
        delivered = False
        try:
            async for item in self.first.stream(model=first, **args):
                delivered = True
                yield item
            return
        except AiProviderError as exc:
            target = None if delivered else self._switch(model, exc)
            if target is None:
                raise
        async for item in self.second.stream(model=target, **args):
            yield item
