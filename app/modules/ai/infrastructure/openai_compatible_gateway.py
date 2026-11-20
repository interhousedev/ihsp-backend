"""Gateway for any OpenAI-compatible `chat/completions` endpoint (Groq, vLLM, ...).

It speaks the same protocol as the OpenRouter gateway but sends only the standard
fields: no `provider`, `models` or `reasoning` object (the effort goes as
`reasoning_effort`), no cache marks, and the headers of the connector instead of
OpenRouter's.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.modules.ai.infrastructure.openrouter import OpenRouterGateway

import httpx

_OPENROUTER_ONLY = frozenset({"provider", "models", "reasoning"})


class OpenAiCompatibleGateway(OpenRouterGateway):
    """Calls `POST {base_url}/chat/completions` of an OpenAI-compatible server."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float,
        headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Configure the HTTP client; pass `client` in tests."""
        super().__init__(
            api_key=api_key or "",
            base_url=base_url,
            app_url="",
            app_title="",
            timeout_seconds=timeout_seconds,
            client=client,
            sleep=sleep,
            cache_models=(),
        )
        auth = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._headers = {**auth, **(headers or {})}

    def _prepared(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The body without what only OpenRouter understands."""
        body = {k: v for k, v in payload.items() if k not in _OPENROUTER_ONLY}
        reasoning = payload.get("reasoning")
        effort = reasoning.get("effort") if isinstance(reasoning, dict) else None
        if isinstance(effort, str):
            body["reasoning_effort"] = effort
        return super()._prepared(body)
