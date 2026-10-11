"""Exa search API client (`POST {base_url}/search`): one HTTP call, the JSON answer.

The key goes only into the `x-api-key` header, never into the body, the URL or a log
line. Errors are raised as `ExaCallError` with the HTTP status (or `timeout`); the web
search adapter turns them into the platform's errors.
"""

from typing import Any, Protocol

import httpx

CONNECT_TIMEOUT_SECONDS = 10.0
SEARCH_PATH = "/search"
DETAILS_CHARS = 200


class ExaCallError(Exception):
    """A search call that did not give a usable answer."""

    def __init__(
        self,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        timeout: bool = False,
        details: str = "",
    ) -> None:
        """Keep the HTTP status, the `Retry-After` seconds and a short reason."""
        super().__init__(details or ("timeout" if timeout else f"HTTP {status}"))
        self.status = status
        self.retry_after = retry_after
        self.timeout = timeout
        self.details = details[:DETAILS_CHARS]


class ExaApi(Protocol):
    """What the web search needs from Exa: one search with a request body."""

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Return the JSON object of the answer (`results`, `costDollars`, ...).

        Raises:
            ExaCallError: The call timed out, failed or gave no JSON object.
        """
        ...


class ExaClient:
    """The real Exa API over httpx; `client` lets a test inject a mocked transport."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure the HTTP client; the key is kept for the header only."""
        self._headers = {"x-api-key": api_key}
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS),
        )

    async def aclose(self) -> None:
        """Close the connection pool (the process is stopping)."""
        await self._client.aclose()

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Send one search and return its JSON object.

        Raises:
            ExaCallError: A timeout, a transport failure, a non-200 status (with the
                `Retry-After` seconds of a 429) or an answer that is not a JSON object.
        """
        try:
            response = await self._client.post(
                SEARCH_PATH, json=body, headers=self._headers
            )
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
        try:
            data = response.json()
        except ValueError as error:
            raise ExaCallError(status=200, details="answer is not JSON") from error
        if not isinstance(data, dict):
            raise ExaCallError(status=200, details="answer is not an object")
        return data


def _retry_after(response: httpx.Response) -> float | None:
    """The `Retry-After` header in seconds, when it is a plain number."""
    raw = response.headers.get("Retry-After")
    try:
        seconds = float(raw) if raw is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and seconds >= 0 else None


def _error_text(response: httpx.Response) -> str:
    """The start of the error body, for the support log only."""
    return " ".join(response.text.split())[:DETAILS_CHARS]
