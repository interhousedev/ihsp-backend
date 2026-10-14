"""Falls back from OpenRouter to the Anthropic API when OpenRouter's credit runs out.

Only a limit failure (402, a 429 left after OpenRouter's own retry, or a key or credit
limit message) of a mapped model (Claude Haiku 5.5) is retried on the fallback, with
the mapped model id; every other error propagates unchanged. A stream falls back only
before its first delta. The answer's usage names the model that ran (`model`), so the
usage ledger records the fallback call.
"""

from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

from app.modules.ai.domain.errors import AiProviderError
from app.shared.contracts.ai import LlmGateway, LlmTuning

import structlog

log = structlog.get_logger(__name__)

LIMIT_STATUSES: Final = frozenset({402, 429})
LIMIT_PHRASES: Final = (
    "insufficient credits",
    "credit limit",
    "key limit",
    "limit exceeded",
    "more credits",
)


def is_limit_error(exc: BaseException) -> bool:
    """True when the provider refused for credit, key limit or rate limit."""
    if not isinstance(exc, AiProviderError):
        return False
    if exc.params.get("status") in LIMIT_STATUSES:
        return True
    details = exc.support_details.lower()
    return any(phrase in details for phrase in LIMIT_PHRASES)


class FallbackLlmGateway:
    """Implements `LlmGateway`: `primary`, then `fallback` on a limit failure."""

    def __init__(
        self,
        primary: LlmGateway,
        fallback: LlmGateway,
        models: Mapping[str, str],
    ) -> None:
        """`models` maps a primary model id to the fallback's id of the same model."""
        self.primary = primary
        self._fallback = fallback
        self._models = dict(models)

    def _target(self, model: str, exc: BaseException) -> str | None:
        target = self._models.get(model)
        if target is None or not is_limit_error(exc):
            return None
        log.warning("ai.fallback_to_anthropic", model=model, target=target)
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
        """`complete` on the primary, on the fallback after a limit failure."""
        args: dict[str, Any] = {
            "system": system,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
            "provider": provider,
            "tuning": tuning,
        }
        try:
            return await self.primary.complete(model=model, **args)
        except AiProviderError as exc:
            target = self._target(model, exc)
            if target is None:
                raise
        return await self._fallback.complete(model=target, **args)

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
        """`complete_json` on the primary, on the fallback after a limit failure."""
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
        try:
            return await self.primary.complete_json(model=model, **args)
        except AiProviderError as exc:
            target = self._target(model, exc)
            if target is None:
                raise
        return await self._fallback.complete_json(model=target, **args)

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
        """Stream from the primary; a limit failure before any item falls back."""
        args: dict[str, Any] = {
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
            "provider": provider,
            "timeout_seconds": timeout_seconds,
            "tuning": tuning,
        }
        delivered = False
        try:
            async for item in self.primary.stream(model=model, **args):
                delivered = True
                yield item
            return
        except AiProviderError as exc:
            target = None if delivered else self._target(model, exc)
            if target is None:
                raise
        async for item in self._fallback.stream(model=target, **args):
            yield item
