"""A scripted LlmGateway that records every request it receives."""

from typing import Any

from app.modules.ai.domain.errors import AiProviderError
from app.shared.contracts.ai import LlmTuning


def text_reply(text: str, *, tokens: int = 100) -> dict[str, Any]:
    """A response with only text."""
    return {
        "text": text,
        "tool_calls": [],
        "usage": {"input": tokens, "output": 20, "cached": 0},
    }


def tool_reply(
    *calls: tuple[str, dict[str, Any]], text: str = "", tokens: int = 100
) -> dict[str, Any]:
    """A response with tool calls (ids are call-1, call-2, ...)."""
    return {
        "text": text,
        "tool_calls": [
            {"id": f"call-{i}", "name": name, "arguments": args}
            for i, (name, args) in enumerate(calls, start=1)
        ],
        "usage": {"input": tokens, "output": 20, "cached": 0},
    }


class ScriptedLlm:
    """Pops queued responses; answers "ok" when the queue is empty."""

    def __init__(self) -> None:
        """Start with an empty script."""
        self.queue: list[dict[str, Any] | Exception] = []
        self.requests: list[dict[str, Any]] = []

    def push(self, *responses: dict[str, Any] | Exception) -> None:
        """Queue responses (or errors to raise)."""
        self.queue.extend(responses)

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
        """Record the request and return the next response."""
        self.requests.append(
            {
                "model": model,
                "system": system,
                "messages": messages,
                "tools": tools,
                "max_tokens": max_tokens,
                "provider": provider,
                "tuning": tuning,
            }
        )
        if not self.queue:
            return text_reply("ok")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def provider_error() -> AiProviderError:
    """An error like the OpenRouter adapter raises."""
    return AiProviderError(support_details="HTTP 503")
