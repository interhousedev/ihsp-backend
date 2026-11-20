"""Which connector, model and reasoning effort a call uses.

Per field the first value wins: the runtime route of the task's pipeline (set by
Administration), the environment value of the task (`AI__TASKS__<TASK>__*`), the
environment value of the pipeline (`AI__PIPELINES__<PIPELINE>__*`), the default
(`AI__DEFAULT__*`). The stored routes and connectors are cached for
`AI__ROUTING_TTL_SECONDS` (30), so a change made in one process applies in every
process within that time; the process that made it drops its cache at once.
"""

import asyncio
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import replace

from app.modules.ai.domain.connectors import (
    Connector,
    EffectiveRoute,
    Pipeline,
    PipelineRoute,
    default_connector_id,
    kind_fits,
    pipeline_of,
)
from app.modules.ai.ports.connectors import (
    ConnectorRuntime,
    RoutingLoader,
    RoutingSnapshot,
)
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import LlmGateway
from app.shared.contracts.web_search import WebSearchGateway

import structlog

log = structlog.get_logger(__name__)

# The route of the call in progress; the usage ledger reads it.
current_route: ContextVar[EffectiveRoute | None] = ContextVar(
    "ai_current_route", default=None
)


class RouteService:
    """Implements `RouteResolver` over the stored routes and the environment."""

    def __init__(
        self,
        settings: Settings,
        loader: RoutingLoader,
        runtime: ConnectorRuntime,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Keep the settings, the loader, the client builder and the time source."""
        self._settings = settings
        self._loader = loader
        self._runtime = runtime
        self._ttl = float(settings.ai.routing_ttl_seconds)
        self._monotonic = monotonic
        self._snapshot: RoutingSnapshot | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        self._clients: dict[tuple[object, ...], LlmGateway | WebSearchGateway] = {}

    def invalidate(self) -> None:
        """Drop the cache: the next call reads the storage."""
        self._snapshot = None
        self._expires_at = 0.0

    async def snapshot(self) -> RoutingSnapshot:
        """The stored connectors and routes (cached for the TTL)."""
        if self._snapshot is not None and self._monotonic() < self._expires_at:
            return self._snapshot
        async with self._lock:
            if self._snapshot is not None and self._monotonic() < self._expires_at:
                return self._snapshot
            try:
                self._snapshot = await self._loader.load()
            except Exception:
                log.exception("ai_routing_read_failed")
                if self._snapshot is None:
                    self._snapshot = RoutingSnapshot()
            self._expires_at = self._monotonic() + self._ttl
            return self._snapshot

    async def connectors(self) -> dict[str, Connector]:
        """The environment's connectors, replaced by the stored row of the same id."""
        found = self._runtime.builtins()
        found.update((await self.snapshot()).connectors)
        return found

    async def route(self, task: AiTask) -> EffectiveRoute:
        """The connector, model and effort of the task's next call."""
        profile = self._settings.ai_profile(task)
        pipeline = pipeline_of(task)
        env = EffectiveRoute(
            pipeline=pipeline,
            connector_id=profile.connector_id or default_connector_id(pipeline),
            model=profile.model,
            reasoning_effort=profile.reasoning_effort,
            source="env",
        )
        return await self._with_runtime(env)

    async def route_of(self, pipeline: Pipeline) -> EffectiveRoute:
        """The pipeline's route from its own and the default values, runtime first."""
        return await self._with_runtime(self.env_route(pipeline))

    def env_route(self, pipeline: Pipeline) -> EffectiveRoute:
        """The pipeline's route without a runtime route."""
        ai = self._settings.ai
        group = ai.pipelines.get(pipeline)
        base = ai.default
        return EffectiveRoute(
            pipeline=pipeline,
            connector_id=(group and group.connector_id)
            or base.connector_id
            or default_connector_id(pipeline),
            model=(group and group.model) or base.model,
            reasoning_effort=(group and group.reasoning_effort)
            or base.reasoning_effort,
            source="env",
        )

    async def _with_runtime(self, env: EffectiveRoute) -> EffectiveRoute:
        snap = await self.snapshot()
        stored = snap.routes.get(env.pipeline)
        if stored is None:
            return env
        connector_id = await self._usable_connector(stored, env.pipeline)
        changed = replace(
            env,
            connector_id=connector_id or env.connector_id,
            model=stored.model or env.model,
            reasoning_effort=stored.reasoning_effort or env.reasoning_effort,
            source="runtime",
            runtime_model=stored.model is not None,
            runtime_effort=stored.reasoning_effort is not None,
        )
        if (
            connector_id is None
            and not changed.runtime_model
            and not changed.runtime_effort
        ):
            return env
        return changed

    async def _usable_connector(
        self, stored: PipelineRoute, pipeline: Pipeline
    ) -> str | None:
        if stored.connector_id is None:
            return None
        found = (await self.connectors()).get(stored.connector_id)
        if found is None or not found.enabled or not kind_fits(found.kind, pipeline):
            log.warning(
                "ai_route_connector_unusable",
                pipeline=pipeline.value,
                connector_id=stored.connector_id,
            )
            return None
        return found.id

    async def client_for(self, connector_id: str) -> LlmGateway | WebSearchGateway:
        """The client of a connector; rebuilt when its row changed."""
        connector = (await self.connectors()).get(connector_id)
        if connector is None:
            raise KeyError(connector_id)
        key: tuple[object, ...] = (
            connector.id,
            connector.kind,
            connector.source,
            connector.base_url,
            connector.enabled,
            connector.has_secret,
            connector.secret_last4,
        )
        client = self._clients.get(key)
        if client is None:
            client = await self._runtime.build(connector)
            self._clients = {k: v for k, v in self._clients.items() if k[0] != key[0]}
            self._clients[key] = client
        return client

    def forget_clients(self, connector_id: str) -> None:
        """Drop the cached clients of a connector (its key changed)."""
        self._clients = {k: v for k, v in self._clients.items() if k[0] != connector_id}
        self.invalidate()
