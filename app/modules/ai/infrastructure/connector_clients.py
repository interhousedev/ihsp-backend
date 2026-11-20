"""Provider clients and tests of the connectors; the environment's connectors.

`openrouter`, `anthropic` and `exa` exist without a row, made from the settings. A
row of the same id replaces them; its key is read from Vault, and a row without a
stored key keeps using the key of the environment.
"""

import time
from collections.abc import AsyncIterator, Mapping
from typing import Any

from app.modules.ai.domain.connectors import (
    BUILTIN_IDS,
    Connector,
    ConnectorKind,
    ProbeResult,
)
from app.modules.ai.domain.errors import ConnectorSecretUnavailableError
from app.modules.ai.infrastructure.anthropic_gateway import AnthropicLlmGateway
from app.modules.ai.infrastructure.exa import ExaClient
from app.modules.ai.infrastructure.exa_rate_limit import ExaRateLimiter, LimitedExa
from app.modules.ai.infrastructure.exa_search import ExaWebSearch
from app.modules.ai.infrastructure.openai_compatible_gateway import (
    OpenAiCompatibleGateway,
)
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.modules.ai.infrastructure.unavailable import UnavailableLlmGateway
from app.modules.ai.ports.connectors import ConnectorSecrets
from app.settings import Settings
from app.shared.contracts.ai import LlmGateway
from app.shared.contracts.web_search import WebSearchGateway

import httpx
import structlog
from redis.asyncio import Redis

log = structlog.get_logger(__name__)

ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
ANTHROPIC_VERSION = "2023-06-01"
_PROBE_TIMEOUT_SECONDS = 10.0
_MIN_KEY_FOR_LAST4 = 8
_ANTHROPIC_PREFIX = "anthropic/"


def _key_of(secret: object) -> str | None:
    value = getattr(secret, "get_secret_value", lambda: None)()
    return str(value) if value else None


class AnthropicModelNames:
    """Implements `LlmGateway` over the Anthropic gateway, with OpenRouter model ids.

    The profiles name models as OpenRouter does (`anthropic/claude-haiku-5.5`); the
    Anthropic API wants its own ids (`ANTHROPIC__MODEL_MAP`). An id not in the map
    loses the `anthropic/` prefix and goes on as it is.
    """

    def __init__(self, inner: LlmGateway, models: Mapping[str, str]) -> None:
        """Keep the gateway and the OpenRouter-id to Anthropic-id table."""
        self._inner = inner
        self._models = dict(models)

    def _name(self, model: str) -> str:
        found = self._models.get(model)
        return found or model.removeprefix(_ANTHROPIC_PREFIX)

    async def complete(self, *, model: str, **kwargs: Any) -> dict[str, Any]:
        """Run `complete` with the Anthropic model id."""
        return await self._inner.complete(model=self._name(model), **kwargs)

    async def complete_json(self, *, model: str, **kwargs: Any) -> dict[str, Any]:
        """Run `complete_json` with the Anthropic model id."""
        return await self._inner.complete_json(model=self._name(model), **kwargs)

    def stream(self, *, model: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Run `stream` with the Anthropic model id."""
        return self._inner.stream(model=self._name(model), **kwargs)


class EnvConnectorRuntime:
    """Implements `ConnectorRuntime` over the settings, Vault and the base clients."""

    def __init__(
        self,
        settings: Settings,
        secrets: ConnectorSecrets,
        *,
        llm: LlmGateway,
        search: WebSearchGateway | None,
        redis: Redis | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        """Keep the settings, the key store and the gateways the environment built."""
        self._settings = settings
        self._secrets = secrets
        self._llm = llm
        self._search = search
        self._redis = redis
        self._http = http
        self._env_anthropic: LlmGateway | None = None

    # - - - the environment's connectors - - -

    def builtins(self) -> dict[str, Connector]:
        """`openrouter`, `anthropic` and `exa` as the settings describe them."""
        s = self._settings
        keys = {cid: self._env_key(cid) for cid in BUILTIN_IDS}
        fake = {"openrouter": s.openrouter.mode == "fake", "exa": s.exa.mode == "fake"}
        titles = {"openrouter": "OpenRouter", "anthropic": "Anthropic", "exa": "Exa"}
        urls = {"openrouter": s.openrouter.base_url, "anthropic": None}
        urls["exa"] = s.exa.base_url
        found: dict[str, Connector] = {}
        for cid in BUILTIN_IDS:
            key = keys[cid]
            found[cid] = Connector(
                id=cid,
                kind=ConnectorKind(cid),
                title=titles[cid],
                base_url=urls[cid],
                enabled=bool(key) or fake.get(cid, False),
                has_secret=bool(key),
                secret_last4=(
                    key[-4:] if key and len(key) >= _MIN_KEY_FOR_LAST4 else None
                ),
                builtin=True,
                source="env",
            )
        return found

    def _env_key(self, connector_id: str) -> str | None:
        s = self._settings
        keys: dict[str, Any] = {
            "openrouter": s.openrouter,
            "anthropic": s.anthropic,
            "exa": s.exa,
        }
        found = keys.get(connector_id)
        return _key_of(found.api_key) if found is not None else None

    def _env_client(self, connector_id: str) -> LlmGateway | WebSearchGateway:
        if connector_id == "openrouter":
            return self._llm
        if connector_id == "exa":
            if self._search is None:
                raise ConnectorSecretUnavailableError(support_details="exa: no client")
            return self._search
        if self._env_anthropic is None:
            key = _key_of(self._settings.anthropic.api_key)
            if key is None:
                self._env_anthropic = UnavailableLlmGateway(
                    "ANTHROPIC__API_KEY is not set"
                )
            else:
                self._env_anthropic = AnthropicModelNames(
                    AnthropicLlmGateway(
                        api_key=key,
                        timeout_seconds=self._settings.openrouter.timeout_seconds,
                    ),
                    self._settings.anthropic.models,
                )
        return self._env_anthropic

    # - - - clients - - -

    async def _stored(self, connector: Connector) -> Mapping[str, Any] | None:
        if connector.source == "env":
            return None
        return await self._secrets.get(connector.id)

    async def build(self, connector: Connector) -> LlmGateway | WebSearchGateway:
        """A client of the connector (a stored one reads its key from Vault)."""
        secret = await self._stored(connector)
        if secret is None and connector.id in BUILTIN_IDS:
            return self._env_client(connector.id)
        secret = secret or {}
        api_key = str(secret["api_key"]) if secret.get("api_key") else None
        headers = {str(k): str(v) for k, v in dict(secret.get("headers") or {}).items()}
        s = self._settings
        timeout = s.openrouter.timeout_seconds
        match connector.kind:
            case ConnectorKind.OPENROUTER:
                return OpenRouterGateway(
                    api_key=api_key or "",
                    base_url=connector.base_url or s.openrouter.base_url,
                    app_url=s.openrouter.app_url,
                    app_title=s.openrouter.app_title,
                    timeout_seconds=timeout,
                    cache_models=s.ai.prompt_cache_models,
                )
            case ConnectorKind.ANTHROPIC:
                return AnthropicModelNames(
                    AnthropicLlmGateway(api_key=api_key or "", timeout_seconds=timeout),
                    s.anthropic.models,
                )
            case ConnectorKind.OPENAI_COMPATIBLE:
                return OpenAiCompatibleGateway(
                    api_key=api_key,
                    base_url=connector.base_url or "",
                    timeout_seconds=timeout,
                    headers=headers,
                )
            case ConnectorKind.EXA:
                client: Any = ExaClient(
                    api_key=api_key or "",
                    base_url=connector.base_url or s.exa.base_url,
                    timeout_seconds=s.exa.timeout_seconds,
                )
                if self._redis is not None:
                    client = LimitedExa(client, ExaRateLimiter(self._redis), s.exa)
                return ExaWebSearch(client, s.web_search, s.exa)
        raise ConnectorSecretUnavailableError(
            support_details=connector.id
        )  # pragma: no cover

    # - - - test - - -

    async def probe(self, connector: Connector) -> ProbeResult:
        """List the models (or run one tiny search); fake mode answers ok."""
        s = self._settings
        if connector.source == "env" and (
            (connector.id == "openrouter" and s.openrouter.mode == "fake")
            or (connector.id == "exa" and s.exa.mode == "fake")
        ):
            return ProbeResult(ok=True, latency_ms=0, error=None)
        started = time.monotonic()
        try:
            secret = await self._stored(connector)
            api_key = (secret or {}).get("api_key") or self._env_key(connector.id)
            headers = dict((secret or {}).get("headers") or {})
            response = await self._probe_request(connector, api_key, headers)
        except Exception as exc:  # the text can name the host, never the key
            return ProbeResult(False, _ms(started), type(exc).__name__)
        ok = response.status_code < 400
        return ProbeResult(
            ok, _ms(started), None if ok else f"HTTP {response.status_code}"
        )

    async def _probe_request(
        self, connector: Connector, api_key: str | None, headers: dict[str, str]
    ) -> httpx.Response:
        s = self._settings
        timeout = httpx.Timeout(_PROBE_TIMEOUT_SECONDS)
        client = self._http or httpx.AsyncClient(timeout=timeout)
        try:
            match connector.kind:
                case ConnectorKind.ANTHROPIC:
                    return await client.get(
                        ANTHROPIC_MODELS_URL,
                        headers={
                            "x-api-key": api_key or "",
                            "anthropic-version": ANTHROPIC_VERSION,
                        },
                    )
                case ConnectorKind.EXA:
                    base = (connector.base_url or s.exa.base_url).rstrip("/")
                    return await client.post(
                        f"{base}/search",
                        headers={"x-api-key": api_key or ""},
                        json={"query": "test", "numResults": 1},
                    )
                case _:
                    base = (connector.base_url or s.openrouter.base_url).rstrip("/")
                    auth = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                    return await client.get(
                        f"{base}/models", headers={**auth, **headers}
                    )
        finally:
            if self._http is None:
                await client.aclose()


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
