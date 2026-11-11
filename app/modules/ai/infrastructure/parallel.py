"""Parallel Search API client (`POST {base_url}/v1/search`): one HTTP call, the JSON.

It is the Exa client with another path: the key goes only into the `x-api-key` header,
and a failed call raises `ExaCallError` (the HTTP status, `Retry-After` or `timeout`),
which the shared allowance (`LimitedExa`) and the adapter turn into platform errors.
"""

import json
from typing import Any
from uuid import uuid4

from app.modules.ai.infrastructure.exa import (
    CONNECT_TIMEOUT_SECONDS,
    ExaApi,
    ExaCallError,
    ExaClient,
    _error_text,
    _retry_after,
)

import httpx

SEARCH_PATH = "/v1/search"

ParallelApi = ExaApi
"""What the Parallel adapter needs: one search with a request body."""


class ParallelClient(ExaClient):
    """The real Parallel API over httpx; `client` lets a test inject a transport."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure the HTTP client; the key is kept for the header only."""
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            client=client,
            path=SEARCH_PATH,
        )


def _rpc_payload(text: str) -> dict[str, Any] | None:
    """The JSON-RPC object of an answer: plain JSON or the last SSE `data:` event."""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                data = json.loads(line[5:].strip())
            except ValueError:
                continue
    return data if isinstance(data, dict) else None


class ParallelMcpClient:
    """Parallel's free MCP endpoint (no key): one `tools/call` of `web_search`.

    It takes the same body as the REST client, sends the objective and the queries and
    returns `{search_id, results}` cut to the body's `max_results`.
    """

    def __init__(
        self,
        *,
        url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure the HTTP client; `session_id` is stable for this process."""
        self._url = url
        self._session_id = f"iht-{uuid4().hex}"
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS),
        )

    async def aclose(self) -> None:
        """Close the connection pool (the process is stopping)."""
        await self._client.aclose()

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Send one search and return `{search_id, results}`.

        Raises:
            ExaCallError: A timeout, a transport failure, a non-200 status, a JSON-RPC
                error, `isError` or an answer without `structuredContent`.
        """
        arguments: dict[str, Any] = {
            "objective": body.get("objective", ""),
            "search_queries": body.get("search_queries", []),
            "session_id": self._session_id,
        }
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "web_search", "arguments": arguments},
        }
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        try:
            response = await self._client.post(self._url, json=payload, headers=headers)
        except httpx.TimeoutException as error:
            raise ExaCallError(timeout=True) from error
        except httpx.HTTPError as error:
            raise ExaCallError(details=f"transport: {type(error).__name__}") from error
        if response.status_code != 200:
            raise ExaCallError(
                status=response.status_code,
                retry_after=_retry_after(response),
                details=_error_text(response),
            )
        content = _structured_content(response.text)
        found = content.get("results")
        limit = body.get("advanced_settings", {}).get("max_results")
        if isinstance(found, list) and isinstance(limit, int):
            content = {**content, "results": found[:limit]}
        return content


def _structured_content(text: str) -> dict[str, Any]:
    """The `structuredContent` of a JSON-RPC tool answer, or `ExaCallError`."""
    message = _rpc_payload(text)
    if message is None:
        raise ExaCallError(status=200, details="answer is not JSON")
    if message.get("error"):
        raise ExaCallError(status=200, details=f"rpc: {message['error']}")
    result = message.get("result")
    if not isinstance(result, dict) or result.get("isError"):
        raise ExaCallError(status=200, details="tool error")
    content = result.get("structuredContent")
    if not isinstance(content, dict):
        raise ExaCallError(status=200, details="answer without structuredContent")
    return content
