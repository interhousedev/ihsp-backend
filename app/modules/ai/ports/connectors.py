"""Ports of the connectors and pipeline routes."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from app.modules.ai.domain.connectors import (
    Connector,
    EffectiveRoute,
    Pipeline,
    PipelineRoute,
    ProbeResult,
)
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import LlmGateway
from app.shared.contracts.web_search import WebSearchGateway
from app.shared.notifications import AuditDraft


class ConnectorRepository(Protocol):
    """The connector rows (only what administrators added or overrode)."""

    async def list(self) -> list[Connector]:
        """Every row, by id."""
        ...

    async def get(self, id: str) -> Connector | None:
        """One row, or None."""
        ...

    async def add(self, connector: Connector, actor_id: UUID) -> None:
        """Insert a row."""
        ...

    async def update(self, connector: Connector) -> None:
        """Replace the row's fields."""
        ...

    async def delete(self, id: str) -> None:
        """Delete the row."""
        ...


class PipelineRouteRepository(Protocol):
    """The runtime routes of the pipelines."""

    async def list(self) -> list[PipelineRoute]:
        """Every route."""
        ...

    async def put(self, route: PipelineRoute) -> None:
        """Insert or replace the pipeline's route."""
        ...

    async def delete(self, pipeline: Pipeline) -> None:
        """Remove the pipeline's route."""
        ...


class ConnectorSecrets(Protocol):
    """The connector keys, in Vault KV v2 under `<kv_prefix>/<connector_id>`."""

    async def get(self, connector_id: str) -> Mapping[str, Any] | None:
        """The secret (`api_key`, optional `headers`), or None."""
        ...

    async def put(self, connector_id: str, secret: Mapping[str, Any]) -> None:
        """Write the secret.

        Raises:
            ConnectorSecretUnavailableError: Vault is off or unreachable.
        """
        ...

    async def delete(self, connector_id: str) -> None:
        """Delete the secret and its versions; a missing one is fine."""
        ...


class ConnectorUnitOfWork(Protocol):
    """One transaction over connectors and routes, with audit events."""

    @property
    def connectors(self) -> ConnectorRepository:
        """The connector repository of the open transaction."""
        ...

    @property
    def routes(self) -> PipelineRouteRepository:
        """The route repository of the open transaction."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events for commit."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...


@dataclass(frozen=True, slots=True)
class RoutingSnapshot:
    """The stored connectors and routes, as one read."""

    connectors: Mapping[str, Connector] = field(default_factory=dict)
    routes: Mapping[Pipeline, PipelineRoute] = field(default_factory=dict)


class RoutingLoader(Protocol):
    """Reads the stored connectors and routes (cached by the route service)."""

    async def load(self) -> RoutingSnapshot:
        """Every row of both tables."""
        ...


class ConnectorRuntime(Protocol):
    """Builds provider clients and the environment's connectors."""

    def builtins(self) -> dict[str, Connector]:
        """The connectors made from the environment, by id."""
        ...

    async def build(self, connector: Connector) -> LlmGateway | WebSearchGateway:
        """A client of the connector (a stored one reads its key from Vault).

        Raises:
            ConnectorSecretUnavailableError: The key cannot be read.
        """
        ...

    async def probe(self, connector: Connector) -> ProbeResult:
        """A tiny request that shows whether the connector answers; no key is echoed."""
        ...


class RouteResolver(Protocol):
    """Used per call by the routed gateways."""

    async def route(self, task: AiTask) -> EffectiveRoute:
        """The connector, model and effort the task's call uses now."""
        ...

    async def route_of(self, pipeline: Pipeline) -> EffectiveRoute:
        """The route of a pipeline's first task (environment values for display)."""
        ...

    async def client_for(self, connector_id: str) -> LlmGateway | WebSearchGateway:
        """The client of a connector."""
        ...

    def invalidate(self) -> None:
        """Drop the cache: the next call reads the storage."""
        ...
