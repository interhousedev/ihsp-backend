"""Anthropic Messages API adapter of the LlmGateway (the fallback of OpenRouter).

The callers speak the OpenAI message format (what OpenRouter takes); this adapter
translates it to the Messages API: the system prompt, `tool_calls` into `tool_use`
blocks, `role: tool` messages into `tool_result` blocks and the function tools into
`input_schema` tools. `cache_control` marks on text parts are kept, and the system
prompt is always a cache breakpoint. The usage comes back in the gateway's shape.
"""

import json
from collections.abc import AsyncIterator
from typing import Any, Final

from app.modules.ai.domain.errors import AiProviderError
from app.modules.ai.infrastructure.openrouter import parse_json_object
from app.shared.ai.prompt_cache import text_part
from app.shared.contracts.ai import LlmTuning

import anthropic
import structlog

log = structlog.get_logger(__name__)

PROVIDER: Final = "anthropic"
SDK_RETRIES: Final = 1
# Claude Haiku 5.5, per million tokens, for prompts up to 100K tokens (cost_micro is
# micro-dollars, so dollars per million tokens are micro-dollars per token).
HAIKU_PRICE_LIMIT: Final = 100_000
HAIKU_INPUT: Final = 0.10
HAIKU_OUTPUT: Final = 0.50
CACHE_READ_FACTOR: Final = 0.1
CACHE_WRITE_FACTOR: Final = 1.25
PRICED_MODELS: Final = ("claude-haiku-5-5",)


class AnthropicLlmGateway:
    """Calls `messages.create` / `messages.stream` of the official SDK."""

    def __init__(
        self, *, api_key: str, timeout_seconds: float, client: Any | None = None
    ) -> None:
        """Configure the SDK client; pass `client` (a fake) in tests."""
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_seconds, max_retries=SDK_RETRIES
        )

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
        """Return {"text", "tool_calls", "usage"}; `provider` is OpenRouter's only."""
        params = build_request(model, system, messages, tools, max_tokens, tuning)
        response = await self._call(self._client.messages.create, params)
        return parse_message(response, model)

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
        """Return {"data", "text", "usage"} for a structured output request."""
        params = build_request(model, system, messages, [], max_tokens, tuning)
        output = params.setdefault("output_config", {})
        output["format"] = {"type": "json_schema", "schema": schema}
        if timeout_seconds is not None:
            params["timeout"] = timeout_seconds
        result = parse_message(
            await self._call(self._client.messages.create, params), model
        )
        return {
            "data": parse_json_object(result["text"]),
            "text": result["text"],
            "usage": result["usage"],
        }

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
        """Yield {"delta": text} items, then {"usage": {...}}."""
        params = build_request(model, system, messages, [], max_tokens, tuning)
        if timeout_seconds is not None:
            params["timeout"] = timeout_seconds
        try:
            async with self._client.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield {"delta": text}
                final = await stream.get_final_message()
        except anthropic.APIError as exc:
            raise _provider_error(exc) from exc
        yield {"usage": usage_of(final.usage, model)}

    async def _call(self, method: Any, params: dict[str, Any]) -> Any:
        try:
            return await method(**params)
        except anthropic.APIError as exc:
            raise _provider_error(exc) from exc


def _provider_error(exc: anthropic.APIError) -> AiProviderError:
    status = getattr(exc, "status_code", None)
    # Never log the prompt: only the status and the error class.
    log.warning("ai.anthropic_error", status=status, error=type(exc).__name__)
    return AiProviderError(
        params={"status": status} if status is not None else None,
        support_details=f"anthropic {status or 'transport'}: {type(exc).__name__}",
    )


def build_request(
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int,
    tuning: LlmTuning | None,
) -> dict[str, Any]:
    """The `messages.create` keyword arguments of one OpenAI-format request.

    No `temperature` (non-default sampling is refused by the newest models) and the
    tool choice stays `auto` (forced choices are refused too).
    """
    extra_system, converted = convert_messages(messages)
    system_parts = [text_part(system, cache=True), *extra_system]
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_parts,
        "messages": converted,
    }
    if tools:
        params["tools"] = [convert_tool(tool) for tool in tools]
        params["tool_choice"] = {"type": "auto"}
    effort = tuning.reasoning_effort if tuning is not None else None
    if effort == "none":
        params["thinking"] = {"type": "disabled"}
        params["output_config"] = {"effort": "low"}
    elif effort == "minimal":
        params["output_config"] = {"effort": "low"}
    elif effort is not None:
        params["output_config"] = {"effort": effort}
    return params


def convert_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """An OpenAI function tool as an Anthropic tool definition."""
    function = tool.get("function") or tool
    converted: dict[str, Any] = {
        "name": function["name"],
        "input_schema": function.get("parameters")
        or {"type": "object", "properties": {}},
    }
    if function.get("description"):
        converted["description"] = function["description"]
    return converted


def convert_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (extra system parts, Anthropic messages) of OpenAI-format messages.

    Consecutive tool results are merged into one user turn.
    """
    system: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            system.extend(_blocks(message.get("content")))
        elif role == "tool":
            result = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id", ""),
                "content": _plain(message.get("content")),
            }
            last = out[-1] if out else None
            if last and last["role"] == "user" and _all_results(last["content"]):
                last["content"].append(result)
            else:
                out.append({"role": "user", "content": [result]})
        elif role == "assistant":
            out.append({"role": "assistant", "content": _assistant_blocks(message)})
        else:
            out.append({"role": "user", "content": _blocks(message.get("content"))})
    return system, out


def _all_results(content: Any) -> bool:
    return isinstance(content, list) and all(
        block.get("type") == "tool_result" for block in content
    )


def _assistant_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = _blocks(message.get("content"))
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        blocks.append(
            {
                "type": "tool_use",
                "id": call.get("id", ""),
                "name": function.get("name", ""),
                "input": arguments if isinstance(arguments, dict) else {},
            }
        )
    return blocks


def _blocks(content: Any) -> list[dict[str, Any]]:
    """Text content blocks; `cache_control` marks are kept, empty text dropped."""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    blocks: list[dict[str, Any]] = []
    for part in content:
        if part.get("type") != "text" or not part.get("text"):
            continue
        block: dict[str, Any] = {"type": "text", "text": part["text"]}
        if part.get("cache_control"):
            block["cache_control"] = dict(part["cache_control"])
        blocks.append(block)
    return blocks


def _plain(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block["text"] for block in _blocks(content))


def parse_message(response: Any, model: str) -> dict[str, Any]:
    """Map a `Message` to the LlmGateway result shape."""
    texts: list[str] = []
    calls: list[dict[str, Any]] = []
    for block in response.content:
        if block.type == "text":
            texts.append(block.text)
        elif block.type == "tool_use":
            arguments = block.input if isinstance(block.input, dict) else {}
            calls.append({"id": block.id, "name": block.name, "arguments": arguments})
    return {
        "text": "".join(texts),
        "tool_calls": calls,
        "usage": usage_of(response.usage, model),
    }


def usage_of(usage: Any, model: str) -> dict[str, Any]:
    """The gateway usage: `input` counts every prompt token, cached or not."""
    fresh = int(getattr(usage, "input_tokens", 0) or 0)
    read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    written = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    output = int(getattr(usage, "output_tokens", 0) or 0)
    result: dict[str, Any] = {
        "input": fresh + read + written,
        "output": output,
        "cached": read,
        "model": model,
        "provider": PROVIDER,
    }
    cost = cost_micro(model, fresh=fresh, read=read, written=written, output=output)
    if cost is not None:
        result["cost_micro"] = cost
    return result


def cost_micro(
    model: str, *, fresh: int, read: int, written: int, output: int
) -> int | None:
    """Micro-dollars of a Haiku 5.5 call; None when the price is not known here."""
    if model not in PRICED_MODELS or fresh + read + written > HAIKU_PRICE_LIMIT:
        return None
    prompt = HAIKU_INPUT * (
        fresh + read * CACHE_READ_FACTOR + written * CACHE_WRITE_FACTOR
    )
    return round(prompt + HAIKU_OUTPUT * output)
