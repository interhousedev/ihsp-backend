"""Chooses the LlmGateway, the WebSearchGateway and the embeddings from the settings."""

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, cast

from app.modules.ai.application.routing import current_route
from app.modules.ai.domain.connectors import EffectiveRoute, Pipeline
from app.modules.ai.infrastructure.anthropic_gateway import AnthropicLlmGateway
from app.modules.ai.infrastructure.exa import ExaApi, ExaClient
from app.modules.ai.infrastructure.exa_contents import (
    CONTENTS_PATH,
    PAGE_CHARS,
    ExaPageReader,
)
from app.modules.ai.infrastructure.exa_rate_limit import ExaRateLimiter, LimitedExa
from app.modules.ai.infrastructure.exa_search import ExaWebSearch
from app.modules.ai.infrastructure.fake_embeddings import FakeEmbeddingGateway
from app.modules.ai.infrastructure.fake_exa import FakeExaClient
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.ai.infrastructure.fake_parallel import FakeParallelClient
from app.modules.ai.infrastructure.fallback_gateway import (
    FallbackLlmGateway,
    is_limit_error,
    is_overload_error,
    mapped_models,
    never,
    same_model,
)
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.modules.ai.infrastructure.openrouter_embeddings import OpenRouterEmbeddings
from app.modules.ai.infrastructure.parallel import (
    ParallelApi,
    ParallelClient,
    ParallelMcpClient,
)
from app.modules.ai.infrastructure.parallel_search import (
    ParallelFirstWebSearch,
    ParallelWebSearch,
)
from app.modules.ai.infrastructure.unavailable import (
    UnavailableExaClient,
    UnavailableLlmGateway,
)
from app.modules.ai.ports.connectors import RouteResolver
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiProviderError, LlmGateway, LlmTuning
from app.shared.contracts.embeddings import EmbeddingGateway
from app.shared.contracts.web_search import (
    SearchCall,
    SearchReply,
    WebSearchGateway,
)

from redis.asyncio import Redis


def make_llm_gateway(settings: Settings, *, required: bool = True) -> LlmGateway:
    """Return the real OpenRouter gateway or the fake one (`OPENROUTER__MODE`).

    With `ANTHROPIC__API_KEY` the real gateway works with the Anthropic API for the
    mapped models (Claude Haiku 5.5): `ANTHROPIC__MODE=fallback` (default) asks
    OpenRouter first and Anthropic after a limit; `default` asks Anthropic first and
    OpenRouter after a rate limit, overload or 5xx. Unmapped models use OpenRouter.

    A real connection without a key stops the start when `required`; a process that
    holds no key (the bot) gets a gateway that fails only when a call reaches it.
    `ANTHROPIC__MODE=default` without its key stops the start the same way.
    """
    config = settings.openrouter
    if config.mode == "fake":
        return FakeLlmGateway()
    if config.api_key is None:
        if not required:
            return UnavailableLlmGateway("OPENROUTER__API_KEY is not set here")
        raise ValueError("OPENROUTER__API_KEY is required when OPENROUTER__MODE=real")
    anthropic_config = settings.anthropic
    if anthropic_config.mode == "default" and anthropic_config.api_key is None:
        if required:
            raise ValueError(
                "ANTHROPIC__API_KEY is required when ANTHROPIC__MODE=default"
            )
    primary = OpenRouterGateway(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        app_url=config.app_url,
        app_title=config.app_title,
        timeout_seconds=config.timeout_seconds,
        cache_models=settings.ai.prompt_cache_models,
    )
    if not anthropic_config.active or anthropic_config.api_key is None:
        return primary
    anthropic = AnthropicLlmGateway(
        api_key=anthropic_config.api_key.get_secret_value(),
        timeout_seconds=config.timeout_seconds,
    )
    models = anthropic_config.models
    if anthropic_config.mode == "default":
        return FallbackLlmGateway(
            anthropic,
            primary,
            primary_route=mapped_models(models),
            secondary_route=same_model,
            switch_on=(
                is_overload_error if anthropic_config.fallback_enabled else never
            ),
        )
    return FallbackLlmGateway(
        primary,
        anthropic,
        primary_route=same_model,
        secondary_route=mapped_models(models),
        switch_on=is_limit_error,
    )


def make_web_search_gateway(
    settings: Settings, redis: Redis | None, *, required: bool = True
) -> WebSearchGateway:
    """The web search: Parallel first, Exa as the fallback and the deep partner.

    Parallel is on in `PARALLEL__MODE=fake` and in `live`: with a key through its API,
    without one through the free MCP endpoint (`PARALLEL__KEYLESS`, on by default).
    Every real API is called through an allowance shared by all processes (Redis), so
    `redis` is required then. See `make_exa_web_search`.
    """
    exa = make_exa_web_search(settings, redis, required=required)
    config = settings.parallel
    if not config.enabled:
        return exa
    client: ParallelApi
    if config.mode == "fake":
        client = FakeParallelClient()
    else:
        if redis is None:
            if required:
                raise ValueError("Redis is required for the Parallel rate limit")
            return exa
        if config.api_key is not None:
            client = LimitedExa(
                ParallelClient(
                    api_key=config.api_key.get_secret_value(),
                    base_url=config.base_url,
                    timeout_seconds=config.timeout_seconds,
                ),
                ExaRateLimiter(redis, prefix="ai:parallel"),
                config,
            )
        else:
            client = LimitedExa(
                ParallelMcpClient(
                    url=config.mcp_url, timeout_seconds=config.timeout_seconds
                ),
                ExaRateLimiter(redis, prefix="ai:parallel-mcp"),
                config.model_copy(update={"max_qps": config.keyless_max_qps}),
            )
    return ParallelFirstWebSearch(
        ParallelWebSearch(client, settings.web_search, config), exa
    )


def make_exa_web_search(
    settings: Settings, redis: Redis | None, *, required: bool = True
) -> WebSearchGateway:
    """The Exa search: the real API in `EXA__MODE=real`, else the deterministic fake.

    A real connection without `EXA__API_KEY` stops the start, like a missing OpenRouter
    key does (unless `required` is False: then searches fail when reached); the key
    itself is never logged.
    """
    config = settings.exa
    client: ExaApi
    if config.mode == "fake":
        client = FakeExaClient()
    else:
        if config.api_key is None:
            if not required:
                client = UnavailableExaClient("EXA__API_KEY is not set here")
                return ExaWebSearch(client, settings.web_search, config)
            raise ValueError("EXA__API_KEY is required when EXA__MODE=real")
        if redis is None:
            raise ValueError("Redis is required for the Exa rate limit")
        client = LimitedExa(
            ExaClient(
                api_key=config.api_key.get_secret_value(),
                base_url=config.base_url,
                timeout_seconds=config.timeout_seconds,
            ),
            ExaRateLimiter(redis),
            config,
        )
    return ExaWebSearch(client, settings.web_search, config)


def make_exa_page_reader(
    settings: Settings, redis: Redis | None, *, required: bool = True
) -> ExaPageReader:
    """Exa contents (full page texts) on the same key and rate limit as the search."""
    config = settings.exa
    client: ExaApi
    if config.mode == "fake":
        client = FakeExaClient()
    elif config.api_key is None:
        if required:
            raise ValueError("EXA__API_KEY is required when EXA__MODE=real")
        client = UnavailableExaClient("EXA__API_KEY is not set here")
    else:
        if redis is None:
            raise ValueError("Redis is required for the Exa rate limit")
        client = LimitedExa(
            ExaClient(
                api_key=config.api_key.get_secret_value(),
                base_url=config.base_url,
                timeout_seconds=config.timeout_seconds,
                path=CONTENTS_PATH,
            ),
            ExaRateLimiter(redis),
            config,
        )
    return ExaPageReader(client, max_characters=PAGE_CHARS)


def make_embedding_gateway(settings: Settings, llm: LlmGateway) -> EmbeddingGateway:
    """Embeddings over the same OpenRouter connection, or the deterministic fake.

    Any gateway that is not the OpenRouter one (the fake, or a test double) gets the
    fake embeddings: only a real connection can embed. The fake reports the profile's
    size and batch size, so the pipeline is shaped as in production.
    """
    profile = settings.ai_profile(AiTask.EMBEDDING)
    if isinstance(llm, RoutedLlmGateway):
        llm = llm.base  # embeddings stay on the environment's OpenRouter connection
    if isinstance(llm, FallbackLlmGateway):
        llm = llm.first if isinstance(llm.first, OpenRouterGateway) else llm.second
    if settings.openrouter.mode == "real" and isinstance(llm, OpenRouterGateway):
        return OpenRouterEmbeddings(llm, profile)
    return FakeEmbeddingGateway(dims=profile.dimensions, batch_size=profile.batch_size)


class RoutedLlmGateway:
    """Implements `LlmGateway`: sends each call where its pipeline's route says.

    The task of the call (`tuning.task`) gives the pipeline; the route (runtime route,
    task, pipeline, default) names the connector and may replace the model and the
    reasoning effort. A call of no known task goes to the environment's gateway.
    """

    def __init__(self, base: LlmGateway, resolver: RouteResolver) -> None:
        """Keep the environment's gateway and the route resolver."""
        self.base = base
        self._resolver = resolver

    def __getattr__(self, name: str) -> Any:
        """Other methods of the environment's gateway (`chat`, `embeddings`)."""
        return getattr(self.base, name)

    async def _target(
        self, model: str, tuning: LlmTuning | None
    ) -> tuple[LlmGateway, str, LlmTuning | None]:
        try:
            task = AiTask(tuning.task) if tuning and tuning.task else None
        except ValueError:
            task = None
        if task is None:
            return self.base, model, tuning
        route = await self._resolver.route(task)
        current_route.set(route)
        client = await self._client(route)
        if route.runtime_model:
            model = route.model
        if route.runtime_effort:
            effort = cast(Any, route.reasoning_effort)
            tuning = replace(
                tuning or LlmTuning(task=task.value), reasoning_effort=effort
            )
        return client, model, tuning

    async def _client(self, route: EffectiveRoute) -> LlmGateway:
        try:
            return cast(LlmGateway, await self._resolver.client_for(route.connector_id))
        except Exception as exc:
            raise AiProviderError(
                support_details=f"connector {route.connector_id}: {type(exc).__name__}"
            ) from exc

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
        """Run `complete` on the routed connector."""
        client, model, tuning = await self._target(model, tuning)
        return await client.complete(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            provider=provider,
            tuning=tuning,
        )

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
        """Run `complete_json` on the routed connector."""
        client, model, tuning = await self._target(model, tuning)
        return await client.complete_json(
            model=model,
            system=system,
            messages=messages,
            schema_name=schema_name,
            schema=schema,
            max_tokens=max_tokens,
            provider=provider,
            timeout_seconds=timeout_seconds,
            tuning=tuning,
        )

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
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run `stream` on the routed connector."""
        client, model, tuning = await self._target(model, tuning)
        async for item in client.stream(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            provider=provider,
            timeout_seconds=timeout_seconds,
            tuning=tuning,
            tools=tools,
        ):
            yield item


class RoutedWebSearchGateway:
    """Implements `WebSearchGateway`: a runtime route of `web_search` wins.

    The route names an Exa connector with its own key; without one the environment's
    search runs.
    """

    def __init__(self, base: WebSearchGateway, resolver: RouteResolver) -> None:
        """Keep the environment's gateway and the route resolver."""
        self._base = base
        self._resolver = resolver

    async def search(self, call: SearchCall) -> SearchReply:
        """Search through the routed connector, or the environment's gateway."""
        route = await self._resolver.route_of(Pipeline.WEB_SEARCH)
        if route.source != "runtime":
            return await self._base.search(call)
        client = cast(
            WebSearchGateway, await self._resolver.client_for(route.connector_id)
        )
        return await client.search(call)
