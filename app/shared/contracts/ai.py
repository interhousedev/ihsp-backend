"""AI contracts (provider: ai module; LlmGateway: OpenRouter adapter)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor
from app.shared.base_error import BaseError, ValidationFailedError

# `none` switches reasoning off for models that reason by default (Claude 5.5, GPT-5.x,
# Gemini 3.x); the gateway sends `reasoning: {"enabled": false}` for it.
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class LlmTuning:
    """Optional request parameters a model profile adds to one call.

    Everything left at its default is not sent (the gateway uses its own values).
    """

    temperature: float | None = None
    reasoning_effort: ReasoningEffort | None = None
    fallbacks: tuple[str, ...] = ()  # tried after the model, in this order
    task: str | None = None  # the AiTask name the call runs for (usage ledger only)


class AiProviderError(BaseError):
    """The language model provider failed or is unavailable."""

    code = "ai/provider-error"
    status = 503
    message_key = "ai-provider-error"


class AiInvalidOutputError(ValidationFailedError):
    """The model answered, but not with the JSON object the request asked for."""

    code = "ai/invalid-output"
    message_key = "ai-invalid-output"


class AiQueries(Protocol):
    """Read access to AI chats for other modules."""

    async def pending_approvals(self, user_id: UUID) -> int:
        """Return how many tool calls wait for the user's approval."""
        ...

    async def chat_for_share(
        self, chat_id: UUID, until_seq: int | None
    ) -> dict[str, Any] | None:
        """Return {"title", "owner_id", "messages": [...]} for a shared chat.

        Each message has role, text and tool_notes (list of str).
        """
        ...

    async def chat_owner(self, chat_id: UUID) -> UUID | None:
        """Return the chat owner's id."""
        ...

    async def chat_transcript(
        self, owner_id: UUID, chat_id: UUID, until_seq: int | None
    ) -> dict[str, Any] | None:
        """Return a chat as plain text for a notebook source.

        Shape: ``{"title", "last_message_at", "last_seq", "messages": [{"seq",
        "role", "text"}]}`` with user and assistant text only (no tool calls, tool
        results or approval cards). None for Administration chats, deleted chats
        and chats of another owner.
        """
        ...


class LlmGateway(Protocol):
    """Language model access (OpenRouter in production, a fake in tests)."""

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
        """Return {"text", "tool_calls": [{"id","name","arguments"}], "usage"}.

        usage is {"input": int, "output": int, "cached": int, "cost_micro": int | None}.
        ``provider`` is the OpenRouter ``provider`` routing object (notebooks send
        ``data_collection: "deny"``). ``tuning`` carries the temperature, reasoning
        effort and fallback models of the task's profile.
        """
        ...

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
        """Ask for a JSON document that matches ``schema`` (strict structured output).

        Returns ``{"data": dict, "text": str, "usage": {...}}``. Raises
        ``AiProviderError`` when the provider fails and ``AiInvalidOutputError`` when
        the answer is not a JSON object.
        """
        ...

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
        """Stream text: ``{"delta": str}`` items, then ``{"usage": {...}}``.

        With ``tools`` (tool choice auto) the last item also carries the assembled
        ``"tool_calls": [{"id", "name", "arguments"}]`` of the response.
        """
        ...


class AdminToolBackend(Protocol):
    """Admin assistant tools (provider: I1 adapter over identity/academic/admin)."""

    async def call(
        self, tool: str, arguments: dict[str, Any], actor: Actor
    ) -> dict[str, Any]:
        """Run an admin tool as the actor."""
        ...
