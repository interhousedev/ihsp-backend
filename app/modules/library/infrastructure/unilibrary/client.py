"""HTTP client of UniLibrary: metadata only, honest, never worked around.

- Base URL from settings; `User-Agent` is ours (`unilibrary_agent()`), `Accept` is JSON.
- It never sends `Origin` or `Referer`, never copies the headers of their front end,
  never retries a `403`, and waits as long as `Retry-After` says.
- It has exactly three read calls: the list, one record, the taxonomy lists. There is
  no way to ask for anything else (doc 3.3, "What we never do").
"""

import asyncio
import re
import time
from collections.abc import Mapping
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Literal

from app.modules.library.infrastructure.unilibrary.call_log import CallLog
from app.modules.library.infrastructure.unilibrary.errors import UpstreamError
from app.modules.library.infrastructure.unilibrary.rate_gate import RateGate
from app.settings import LibrarySettings
from app.shared.clock import Clock

import httpx

LIST_PATH = "/api/user/guest-publisher-resources-with-media"
RESOURCE_PATH = "/api/user/guest-publisher-resources"
TAXONOMY_PATH = "/api/crm/{name}/lists"

TaxonomyName = Literal["resource-types", "resource-fields", "resource-languages"]
Params = Mapping[str, str | int]
_RECORD_ID = re.compile(r"[0-9]{1,20}")


def make_http_client(settings: LibrarySettings) -> httpx.AsyncClient:
    """The connection pool to the UniLibrary API (no redirects, bounded)."""
    return httpx.AsyncClient(
        base_url=settings.unilibrary_base_url,
        follow_redirects=False,
        limits=httpx.Limits(
            max_connections=max(settings.unilibrary_concurrency, 1),
            max_keepalive_connections=max(settings.unilibrary_concurrency, 1),
        ),
    )


class UniLibraryClient:
    """Reads lists, records and taxonomies as parsed JSON."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        gate: RateGate,
        calls: CallLog,
        settings: LibrarySettings,
        clock: Clock,
    ) -> None:
        """Take the pool, the request budget, the call log and the timeouts."""
        self.http = http
        self.gate = gate
        self.calls = calls
        self.clock = clock
        self.list_timeout = settings.unilibrary_list_timeout
        self.detail_timeout = settings.unilibrary_detail_timeout
        self._headers = {
            "User-Agent": settings.unilibrary_agent(),
            "Accept": "application/json",
        }

    async def aclose(self) -> None:
        """Close the connection pool."""
        await self.http.aclose()

    async def list_resources(self, query: Params) -> object:
        """`guest-publisher-resources-with-media` with the given query."""
        return await self._get(LIST_PATH, query, self.list_timeout)

    async def resource(self, external_id: str, language: str) -> object | None:
        """One record; None when UniLibrary answers 404 or the id cannot exist."""
        if not _RECORD_ID.fullmatch(external_id):
            return None
        path = f"{RESOURCE_PATH}/{external_id}"
        return await self._get(
            path, {"language": language}, self.detail_timeout, missing_ok=True
        )

    async def taxonomy(self, name: TaxonomyName) -> object:
        """`crm/{name}/lists`: every row, in every language."""
        return await self._get(TAXONOMY_PATH.format(name=name), {}, self.detail_timeout)

    async def _get(
        self, path: str, params: Params, timeout: float, *, missing_ok: bool = False
    ) -> object | None:
        started = time.perf_counter()
        ok = False
        try:
            async with self.gate.slot():
                response = await self._send(path, params, timeout)
            payload = self._read(response, missing_ok=missing_ok)
            ok = True
            return payload
        finally:
            ms = round((time.perf_counter() - started) * 1000)
            await self.calls.record(ok=ok, ms=ms, path=path)

    async def _send(self, path: str, params: Params, timeout: float) -> httpx.Response:
        try:
            async with asyncio.timeout(timeout):
                return await self.http.get(
                    path, params=dict(params), headers=self._headers, timeout=timeout
                )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise UpstreamError("timeout", detail=path) from exc
        except httpx.TransportError as exc:
            raise UpstreamError("network", detail=f"{path}: {exc!r}") from exc

    def _read(self, response: httpx.Response, *, missing_ok: bool) -> object | None:
        status = response.status_code
        if status == 404 and missing_ok:
            return None
        retry_after = self._retry_after(response)
        if status == 403:
            raise UpstreamError("forbidden", status=status)
        if status == 429:
            raise UpstreamError("rate_limited", status=status, retry_after=retry_after)
        if status >= 500:
            raise UpstreamError("server", status=status, retry_after=retry_after)
        if status != 200:
            raise UpstreamError("bad_status", status=status)
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise UpstreamError("bad_payload", status=status) from exc
        return payload

    def _retry_after(self, response: httpx.Response) -> int | None:
        """Seconds from `Retry-After`: a number or an HTTP date."""
        value = response.headers.get("retry-after", "").strip()
        if value.isdecimal():
            return int(value)
        try:
            moment: datetime = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        return max(int((moment - self.clock.now()).total_seconds()), 0) or None
