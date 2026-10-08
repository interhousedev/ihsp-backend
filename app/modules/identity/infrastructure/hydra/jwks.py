"""Cached JWKS of Hydra (public signing keys of access tokens)."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from app.modules.identity.domain.errors import HydraUnavailableError
from app.shared.clock import Clock

import httpx
from joserfc.jwk import KeySet

MIN_REFETCH = timedelta(seconds=30)


class JwksCache:
    """Fetches ``{public_url}/.well-known/jwks.json`` and keeps it for a while."""

    def __init__(
        self,
        *,
        public_url: str,
        ttl_seconds: int,
        clock: Clock,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Remember where to fetch the keys and how long to trust them."""
        self._url = f"{public_url.rstrip('/')}/.well-known/jwks.json"
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock
        self._http = client  # created on first use: building a TLS context is slow
        self._keys: KeySet | None = None
        self._fetched_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def key_set(self, *, force: bool = False) -> KeySet:
        """Return the cached key set, refetching when stale.

        ``force`` (unknown key id) refetches at most once per ``MIN_REFETCH``, so
        tokens with random key ids cannot make us hammer Hydra.
        """
        now = self._clock.now()
        if self._can_reuse(now, force):
            assert self._keys is not None
            return self._keys
        async with self._lock:
            now = self._clock.now()
            if self._can_reuse(now, force):
                assert self._keys is not None
                return self._keys
            self._keys = await self._fetch()
            self._fetched_at = now
            return self._keys

    def _can_reuse(self, now: datetime, force: bool) -> bool:
        if self._keys is None or self._fetched_at is None:
            return False
        age = now - self._fetched_at
        return age < (MIN_REFETCH if force else self._ttl)

    async def _fetch(self) -> KeySet:
        try:
            if self._http is None:
                self._http = httpx.AsyncClient(timeout=5.0)
            response = await self._http.get(self._url)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HydraUnavailableError(
                support_details=f"jwks fetch failed: {exc!r}"
            ) from exc
        return KeySet.import_key_set(data)  # type: ignore[arg-type]
