"""OpenRouter adapter of the LlmGateway (OpenAI-compatible chat completions)."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.ai.domain.errors import AiProviderError

import httpx
import structlog

log = structlog.get_logger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_RETRY_SECONDS = 2.0
MAX_RETRY_SECONDS = 10.0
TEMPERATURE = 0.2


class OpenRouterGateway:
    """Calls `POST {base_url}/chat/completions` with tools and prompt caching."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        app_url: str,
        app_title: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Configure the HTTP client; pass `client` in tests."""
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": app_url,
            "X-OpenRouter-Title": app_title,
            "X-Title": app_title,
        }
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Return {"text", "tool_calls", "usage"} for one model request."""
        payload = build_payload(model, system, messages, tools, max_tokens)
        data = await self._post(payload)
        return parse_response(data)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"
        for attempt in (1, 2):
            try:
                response = await self._client.post(
                    url, json=payload, headers=self._headers
                )
            except httpx.HTTPError as exc:
                if attempt == 1:
                    await self._sleep(DEFAULT_RETRY_SECONDS)
                    continue
                raise AiProviderError(support_details=f"transport: {exc!r}") from exc
            if response.status_code in RETRY_STATUSES and attempt == 1:
                await self._sleep(_retry_after(response))
                continue
            return _checked(response)
        raise AiProviderError(support_details="unreachable")  # pragma: no cover


def build_payload(
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int,
) -> dict[str, Any]:
    """Build the request body; Anthropic models get a cache breakpoint on the system.

    One breakpoint on the last system part caches the tools and the system prompt
    together, because the provider caches the prefix `tools, system, messages`.
    """
    system_content: Any = system
    if model.startswith("anthropic/"):
        system_content = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system_content}, *messages],
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _retry_after(response: httpx.Response) -> float:
    try:
        seconds = float(response.headers.get("Retry-After", DEFAULT_RETRY_SECONDS))
    except ValueError:
        return DEFAULT_RETRY_SECONDS
    return min(max(seconds, 0.0), MAX_RETRY_SECONDS)


def _checked(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise AiProviderError(
            support_details=f"HTTP {response.status_code}: not JSON"
        ) from exc
    error = data.get("error") if isinstance(data, dict) else None
    if response.status_code != 200 or error:
        _log_error(response.status_code, error)
        raise AiProviderError(
            params={"status": response.status_code},
            support_details=f"HTTP {response.status_code}: {_error_text(error)}",
        )
    return data  # type: ignore[no-any-return]


def _error_text(error: Any) -> str:
    if isinstance(error, dict):
        return str(error.get("message", error))
    return str(error)


def _log_error(status: int, error: Any) -> None:
    # Never log the prompt: only the status and the provider's message.
    log.warning("ai.openrouter_error", status=status, error=_error_text(error))


def parse_response(data: dict[str, Any]) -> dict[str, Any]:
    """Map an OpenRouter response to the LlmGateway result shape."""
    choices = data.get("choices") or []
    if not choices:
        raise AiProviderError(support_details="response without choices")
    choice = choices[0]
    if choice.get("error") or choice.get("finish_reason") == "error":
        raise AiProviderError(
            support_details=f"model error: {_error_text(choice.get('error'))}"
        )
    message = choice.get("message") or {}
    return {
        "text": message.get("content") or "",
        "tool_calls": [_tool_call(c) for c in message.get("tool_calls") or []],
        "usage": _usage(data.get("usage") or {}),
    }


def _tool_call(raw: dict[str, Any]) -> dict[str, Any]:
    function = raw.get("function") or {}
    call: dict[str, Any] = {
        "id": raw.get("id", ""),
        "name": function.get("name", ""),
        "arguments": {},
    }
    try:
        parsed = json.loads(function.get("arguments") or "{}")
    except json.JSONDecodeError:
        call["error"] = "the arguments were not valid JSON"
        return call
    if isinstance(parsed, dict):
        call["arguments"] = parsed
    else:
        call["error"] = "the arguments must be a JSON object"
    return call


def _usage(raw: dict[str, Any]) -> dict[str, int]:
    details = raw.get("prompt_tokens_details") or {}
    return {
        "input": int(raw.get("prompt_tokens", 0)),
        "output": int(raw.get("completion_tokens", 0)),
        "cached": int(details.get("cached_tokens", 0)),
    }
