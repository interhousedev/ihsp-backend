"""Parallel Search API client (`POST {base_url}/v1/search`): one HTTP call, the JSON.

It is the Exa client with another path: the key goes only into the `x-api-key` header,
and a failed call raises `ExaCallError` (the HTTP status, `Retry-After` or `timeout`),
which the shared allowance (`LimitedExa`) and the adapter turn into platform errors.
"""

from app.modules.ai.infrastructure.exa import ExaApi, ExaClient

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
