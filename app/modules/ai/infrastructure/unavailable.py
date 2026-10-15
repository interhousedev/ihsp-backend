"""Stand-ins for the LLM and Exa in a process that holds no key (the Telegram bot).

They let such a process start and serve its non-AI screens; any call that reaches
them fails with the reason, so a missing key shows up at use, not at start.
"""

from collections.abc import AsyncIterator
from typing import Any

from app.modules.ai.infrastructure.exa import ExaCallError
from app.shared.base_error import BaseError
from app.shared.contracts.ai import AiProviderError, LlmTuning


class UnavailableLlmGateway:
    """An LlmGateway whose every call raises AiProviderError with the reason."""

    def __init__(self, reason: str) -> None:
        """Keep the reason the calls report (no secret is ever part of it)."""
        self._reason = reason

    def _error(self) -> BaseError:
        return AiProviderError(support_details=self._reason)

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
        """Raise AiProviderError: this process has no model access."""
        raise self._error()

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
        """Raise AiProviderError: this process has no model access."""
        raise self._error()

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
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Raise AiProviderError when the stream is started: no model access."""
        raise self._error()
        yield {}  # pragma: no cover - makes this an async generator


class UnavailableExaClient:
    """An ExaApi whose every search raises ExaCallError with the reason."""

    def __init__(self, reason: str) -> None:
        """Keep the reason the calls report (no secret is ever part of it)."""
        self._reason = reason

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Raise ExaCallError: this process has no web search access."""
        raise ExaCallError(details=self._reason)
