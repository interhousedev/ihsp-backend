"""OpenRouter adapter of the LlmGateway (OpenAI-compatible chat completions)."""

import asyncio
import json
import re
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Sequence,
)
from contextlib import aclosing
from typing import Any, NoReturn

from app.modules.ai.domain.errors import AiInvalidOutputError, AiProviderError
from app.settings_ai import DEFAULT_CACHE_MODELS
from app.shared.ai.prompt_cache import supports_prompt_cache, text_part
from app.shared.contracts.ai import LlmTuning
from app.shared.retry_after import parse_retry_after

import httpx
import structlog

log = structlog.get_logger(__name__)

_FENCE = re.compile(r"```(?:json|JSON)?[ \t]*\n?(.*?)```", re.DOTALL)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_RETRY_SECONDS = 2.0
MAX_RETRY_SECONDS = 10.0
TEMPERATURE = 0.2
CONNECT_TIMEOUT_SECONDS = 10.0
MICRO = 1_000_000
# OpenRouter's 404 when `provider.require_parameters` finds no endpoint that takes
# every parameter of the request (the newest models refuse `temperature`).
UNSUPPORTED_PARAMETERS = "No endpoints found that can handle the requested parameters"
# OpenRouter's 400 for `reasoning: {"enabled": false}` on a model that always reasons
# (Claude Sonnet 5.5, Gemini 3.x); the smallest budget it takes is `effort: low`.
REASONING_MANDATORY = "Reasoning is mandatory"
REASONING_OFF: dict[str, Any] = {"enabled": False}
REASONING_LEAST: dict[str, Any] = {"effort": "low"}


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
        cache_models: Sequence[str] = DEFAULT_CACHE_MODELS,
    ) -> None:
        """Configure the HTTP client; pass `client` in tests.

        `cache_models` are the model id prefixes that get `cache_control` marks.
        """
        self._cache_models = tuple(cache_models)
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
        # Models whose endpoints refuse `temperature` (Claude 5.5, GPT-5.x): learned
        # from one 404 and never sent again in this process.
        self._no_temperature: set[str] = set()
        # Models that cannot switch reasoning off (`reasoning: {"enabled": false}`
        # answers 400): they get the smallest effort instead, learned the same way.
        self._always_reason: set[str] = set()

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def chat(
        self, payload: dict[str, Any], *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        """Send a prepared request body and return the checked JSON response.

        For callers that need fields beyond text and tools (the web search reads the
        message `annotations`). Retries and error mapping are the same as `complete`.
        """
        return await self._post(payload, timeout_seconds=timeout_seconds)

    async def embeddings(
        self, payload: dict[str, Any], *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        """`POST /embeddings` with a prepared body; returns the checked JSON response.

        Same key, retries and error mapping as the chat calls (`OpenRouterEmbeddings`
        builds the body and reads the vectors).
        """
        return await self._post(
            payload, timeout_seconds=timeout_seconds, path="/embeddings"
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
        """Return {"text", "tool_calls", "usage"} for one model request."""
        payload = build_payload(
            model, system, messages, tools, max_tokens, tuning, self._cache_models
        )
        if provider is not None:
            payload["provider"] = provider
        data = await self._post(payload)
        return parse_response(data)

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
        """Return {"data", "text", "usage"} for a strict JSON schema request.

        Raises:
            AiProviderError: The provider failed.
            AiInvalidOutputError: The answer holds no JSON object.
        """
        payload = build_payload(
            model, system, messages, [], max_tokens, tuning, self._cache_models
        )
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        }
        if provider is not None:
            payload["provider"] = provider
        data = await self._post(payload, timeout_seconds=timeout_seconds)
        result = parse_response(data)
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
        """Yield {"delta": text} items, then {"usage": {...}} (server-sent events).

        A failed connection is retried once, but only before the first delta.
        """
        payload = build_payload(
            model, system, messages, [], max_tokens, tuning, self._cache_models
        )
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        if provider is not None:
            payload["provider"] = provider
        for attempt in (1, 2):
            delivered = False
            try:
                async with aclosing(
                    self._stream_once(payload, timeout_seconds)
                ) as items:  # a consumer that stops early still frees the connection
                    async for item in items:
                        delivered = delivered or "delta" in item
                        yield item
                return
            except _RetryLater as later:
                if delivered or attempt == 2:
                    raise later.error from None
                await self._sleep(later.seconds)

    def _prepared(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The body adjusted to what the model's endpoints are known to accept."""
        model = payload.get("model")
        if model in self._no_temperature and "temperature" in payload:
            payload = {k: v for k, v in payload.items() if k != "temperature"}
        if model in self._always_reason and payload.get("reasoning") == REASONING_OFF:
            payload = {**payload, "reasoning": REASONING_LEAST}
        return payload

    def _learn_refusal(self, payload: dict[str, Any], status: int, error: Any) -> bool:
        """Remember a parameter the model refuses; True when a retry makes sense.

        A 404 "No endpoints found that can handle the requested parameters" (with
        `provider.require_parameters`) means an endpoint does not take one of the
        parameters: the newest models refuse `temperature`. A 400 "Reasoning is
        mandatory" means `reasoning: {"enabled": false}` is not accepted: the model
        gets the smallest effort instead.
        """
        model = str(payload.get("model", ""))
        text = _error_text(error)
        if (
            status == 404
            and "temperature" in payload
            and UNSUPPORTED_PARAMETERS in text
        ):
            self._no_temperature.add(model)
            log.warning("ai.openrouter_temperature_dropped", model=model)
            return True
        if (
            status == 400
            and payload.get("reasoning") == REASONING_OFF
            and REASONING_MANDATORY in text
        ):
            self._always_reason.add(model)
            log.warning("ai.openrouter_reasoning_kept", model=model)
            return True
        return False

    async def _raise_stream_error(
        self, response: httpx.Response, payload: dict[str, Any]
    ) -> NoReturn:
        """Raise the failure of a non-200 stream; a learned refusal retries at once."""
        error = await _stream_status_error(response)
        if isinstance(error, AiProviderError) and self._learn_refusal(
            payload, response.status_code, error.support_details
        ):
            raise _RetryLater(0.0, error)
        raise error

    async def _stream_once(
        self, payload: dict[str, Any], timeout_seconds: float | None
    ) -> AsyncGenerator[dict[str, Any], None]:
        url = f"{self._base_url}/chat/completions"
        payload = self._prepared(payload)
        try:
            async with self._client.stream(
                "POST",
                url,
                json=payload,
                headers=self._headers,
                **_timeout_args(timeout_seconds),
            ) as response:
                if response.status_code != 200:
                    await self._raise_stream_error(response, payload)
                parser = SseParser()
                async for line in response.aiter_lines():
                    for item in parser.feed(line):
                        yield item
                    if parser.done:
                        break
                for item in parser.finish():
                    yield item
        except httpx.HTTPError as exc:
            raise _RetryLater(
                DEFAULT_RETRY_SECONDS,
                AiProviderError(support_details=f"transport: {exc!r}"),
            ) from exc

    async def _post(
        self,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
        path: str = "/chat/completions",
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        payload = self._prepared(payload)
        for attempt in (1, 2):
            try:
                response = await self._client.post(
                    url,
                    json=payload,
                    headers=self._headers,
                    **_timeout_args(timeout_seconds),
                )
            except httpx.HTTPError as exc:
                if attempt == 1:
                    await self._sleep(DEFAULT_RETRY_SECONDS)
                    continue
                raise AiProviderError(support_details=f"transport: {exc!r}") from exc
            if response.status_code in RETRY_STATUSES and attempt == 1:
                await self._sleep(_retry_after(response))
                continue
            if attempt == 1 and self._learn_refusal(
                payload, response.status_code, _error_of(response)
            ):
                payload = self._prepared(payload)
                continue
            return _checked(response)
        raise AiProviderError(support_details="unreachable")  # pragma: no cover


def build_payload(
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int,
    tuning: LlmTuning | None = None,
    cache_models: Sequence[str] = DEFAULT_CACHE_MODELS,
) -> dict[str, Any]:
    """Build the request body; caching models get a cache breakpoint on the system.

    `tuning` (from the task's model profile) sets the temperature, the reasoning effort
    and the fallback models (OpenRouter's `models` list, the model first).

    One breakpoint on the last system part caches the tools and the system prompt
    together, because the provider caches the prefix `tools, system, messages`.
    """
    system_content: Any = system
    if supports_prompt_cache(model, cache_models):  # `AI__PROMPT_CACHE_MODELS`
        system_content = [text_part(system, cache=True)]
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system_content}, *messages],
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
    }
    if tuning is not None:
        _apply_tuning(payload, model, tuning)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _apply_tuning(payload: dict[str, Any], model: str, tuning: LlmTuning) -> None:
    """Add what the model profile sets; unset parts keep the gateway's defaults."""
    if tuning.temperature is not None:
        payload["temperature"] = tuning.temperature
    if tuning.reasoning_effort == "none":
        payload["reasoning"] = dict(REASONING_OFF)
    elif tuning.reasoning_effort is not None:
        payload["reasoning"] = {"effort": tuning.reasoning_effort}
    if tuning.fallbacks:
        payload["models"] = [model, *tuning.fallbacks]


class _RetryLater(Exception):
    """A failure that may be retried after ``seconds``; ``error`` is the final one."""

    def __init__(self, seconds: float, error: AiProviderError) -> None:
        super().__init__(error.support_details)
        self.seconds = seconds
        self.error = error


def _timeout_args(seconds: float | None) -> dict[str, Any]:
    """The per-request timeout; without it the client's default applies."""
    if seconds is None:
        return {}
    return {"timeout": httpx.Timeout(seconds, connect=CONNECT_TIMEOUT_SECONDS)}


def _retry_after(response: httpx.Response) -> float:
    seconds = parse_retry_after(response.headers.get("Retry-After"))
    if seconds is None:
        return DEFAULT_RETRY_SECONDS
    return min(seconds, MAX_RETRY_SECONDS)


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


def _error_of(response: httpx.Response) -> Any:
    """The `error` object of a response body, or None when there is none."""
    try:
        data = response.json()
    except ValueError:
        return None
    return data.get("error") if isinstance(data, dict) else None


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
    usage = {
        "input": int(raw.get("prompt_tokens", 0)),
        "output": int(raw.get("completion_tokens", 0)),
        "cached": int(details.get("cached_tokens", 0)),
    }
    if raw.get("cost") is not None:
        usage["cost_micro"] = round(float(raw["cost"]) * MICRO)
    return usage


def parse_json_object(text: str) -> dict[str, Any]:
    """Return the JSON object in a model answer.

    Accepts a bare object, an object inside a Markdown code fence and an object with
    some text before or after it. Anything else raises ``AiInvalidOutputError``
    (the message never holds the text).
    """
    body = _unfenced(text)
    try:
        whole = json.loads(body)
    except ValueError:
        found = _first_object(body)
        if found is None:
            raise AiInvalidOutputError(support_details="not a JSON object") from None
        return found
    if not isinstance(whole, dict):
        raise AiInvalidOutputError(support_details="not a JSON object")
    return whole


def _unfenced(text: str) -> str:
    """Return the content of the first Markdown code fence, else the trimmed text."""
    match = _FENCE.search(text)
    return (match.group(1) if match else text).strip()


def _first_object(text: str) -> dict[str, Any] | None:
    """Return the first JSON object that starts at some ``{`` of the text."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    return None


async def _stream_status_error(response: httpx.Response) -> Exception:
    """Build the error for a non-200 streamed response (retryable ones wrap it)."""
    status = response.status_code
    body = await response.aread()
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = None
    error = parsed.get("error") if isinstance(parsed, dict) else None
    _log_error(status, error)
    failure = AiProviderError(
        params={"status": status},
        support_details=f"HTTP {status}: {_error_text(error) if error else 'no body'}",
    )
    if status in RETRY_STATUSES:
        return _RetryLater(_retry_after(response), failure)
    return failure


class SseParser:
    """Reads the server-sent events of a streamed completion, line by line.

    Blank lines, ``:`` keep-alive comments and other SSE fields are ignored; the
    stream ends at ``data: [DONE]``. ``feed`` returns the ``{"delta": text}`` items of
    a line and ``finish`` returns the final ``{"usage": {...}}``.
    """

    def __init__(self) -> None:
        """Start before the first line."""
        self.done = False
        self._finished = False
        self._usage: dict[str, Any] = {}

    def feed(self, line: str) -> list[dict[str, Any]]:
        """Return the items of one line."""
        text = line.strip()
        if not text.startswith("data:"):
            return []
        body = text[len("data:") :].strip()
        if body == "[DONE]":
            self.done = self._finished = True
            return []
        chunk = _parse_chunk(body)
        if isinstance(chunk.get("usage"), dict):
            self._usage = chunk["usage"]
        choice = (chunk.get("choices") or [{}])[0]
        if choice.get("finish_reason"):
            self._finished = True
        content = (choice.get("delta") or {}).get("content")
        return [{"delta": content}] if content else []

    def finish(self) -> list[dict[str, Any]]:
        """Return the usage item; a stream cut short is a provider error."""
        if not self._finished:
            raise AiProviderError(support_details="stream ended early")
        return [{"usage": _usage(self._usage)}]


def _parse_chunk(body: str) -> dict[str, Any]:
    """Parse one event; an error object (also inside a choice) is a provider error."""
    try:
        chunk = json.loads(body)
    except ValueError as exc:
        raise AiProviderError(support_details="stream chunk is not JSON") from exc
    if not isinstance(chunk, dict):
        raise AiProviderError(support_details="stream chunk is not an object")
    choice = (chunk.get("choices") or [{}])[0]
    error = chunk.get("error") or choice.get("error")
    if error or choice.get("finish_reason") == "error":
        _log_error(200, error)
        raise AiProviderError(support_details=f"stream error: {_error_text(error)}")
    return chunk
