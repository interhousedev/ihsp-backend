"""In-memory fakes of the connector repositories, key store, clients and loader."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import TracebackType
from typing import Any, Self, cast
from uuid import UUID

from app.modules.ai.domain.connectors import (
    BUILTIN_IDS,
    Connector,
    ConnectorKind,
    Pipeline,
    PipelineRoute,
    ProbeResult,
)
from app.modules.ai.domain.errors import ConnectorSecretUnavailableError
from app.modules.ai.ports.connectors import RoutingSnapshot
from app.shared.contracts.ai import LlmGateway
from app.shared.contracts.web_search import WebSearchGateway
from app.shared.notifications import AuditDraft


@dataclass
class ConnectorWorld:
    """What the fake database holds; every unit of work shares it."""

    connectors: dict[str, Connector] = field(default_factory=dict)
    routes: dict[Pipeline, PipelineRoute] = field(default_factory=dict)
    audit: list[AuditDraft] = field(default_factory=list)
    loads: int = 0


class FakeConnectorRepository:
    """Implements `ConnectorRepository` in memory."""

    def __init__(self, world: ConnectorWorld) -> None:
        """Keep the world."""
        self.world = world

    async def list(self) -> list[Connector]:
        """Every row, by id."""
        return sorted(self.world.connectors.values(), key=lambda c: c.id)

    async def get(self, id: str) -> Connector | None:
        """One row, or None."""
        return self.world.connectors.get(id)

    async def add(self, connector: Connector, actor_id: UUID) -> None:
        """Insert a row."""
        self.world.connectors[connector.id] = connector

    async def update(self, connector: Connector) -> None:
        """Replace the row."""
        self.world.connectors[connector.id] = connector

    async def delete(self, id: str) -> None:
        """Delete the row."""
        self.world.connectors.pop(id, None)


class FakeRouteRepository:
    """Implements `PipelineRouteRepository` in memory."""

    def __init__(self, world: ConnectorWorld) -> None:
        """Keep the world."""
        self.world = world

    async def list(self) -> list[PipelineRoute]:
        """Every route."""
        return list(self.world.routes.values())

    async def put(self, route: PipelineRoute) -> None:
        """Insert or replace."""
        self.world.routes[route.pipeline] = route

    async def delete(self, pipeline: Pipeline) -> None:
        """Remove."""
        self.world.routes.pop(pipeline, None)


class FakeConnectorUow:
    """Implements `ConnectorUnitOfWork`; changes apply at once, audit at commit."""

    def __init__(self, world: ConnectorWorld) -> None:
        """Build the repositories on the world."""
        self.world = world
        self.connectors = FakeConnectorRepository(world)
        self.routes = FakeRouteRepository(world)
        self._audit: list[AuditDraft] = []
        self.committed = False

    async def __aenter__(self) -> Self:
        """Open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close."""

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        self._audit.extend(drafts)

    async def commit(self) -> None:
        """Write the audit events."""
        self.committed = True
        self.world.audit.extend(self._audit)


class FakeSecrets:
    """Implements `ConnectorSecrets` in memory; `available=False` is a dead Vault."""

    def __init__(self, *, available: bool = True) -> None:
        """Start empty."""
        self.store: dict[str, dict[str, Any]] = {}
        self.available = available

    def _check(self) -> None:
        if not self.available:
            raise ConnectorSecretUnavailableError()

    async def get(self, connector_id: str) -> Mapping[str, Any] | None:
        """The secret, or None."""
        self._check()
        return self.store.get(connector_id)

    async def put(self, connector_id: str, secret: Mapping[str, Any]) -> None:
        """Write the secret."""
        self._check()
        self.store[connector_id] = dict(secret)

    async def delete(self, connector_id: str) -> None:
        """Delete the secret."""
        self._check()
        self.store.pop(connector_id, None)


class FakeRuntime:
    """Implements `ConnectorRuntime`: environment connectors, recorded clients."""

    def __init__(self, base: LlmGateway | None = None) -> None:
        """The environment has OpenRouter (with a key), Anthropic (without) and Exa."""
        self.base = base
        self.built: list[str] = []
        self.clients: dict[str, Any] = {}
        self.probe_result = ProbeResult(ok=True, latency_ms=12, error=None)

    def builtins(self) -> dict[str, Connector]:
        """The three built-in connectors."""
        return {
            cid: Connector(
                id=cid,
                kind=ConnectorKind(cid),
                title=cid.title(),
                base_url=None,
                enabled=cid != "anthropic",
                has_secret=cid != "anthropic",
                secret_last4="a1b2" if cid != "anthropic" else None,
                builtin=True,
                source="env",
            )
            for cid in BUILTIN_IDS
        }

    async def build(self, connector: Connector) -> LlmGateway | WebSearchGateway:
        """A recorded client per connector id."""
        self.built.append(connector.id)
        return cast(
            LlmGateway | WebSearchGateway,
            self.clients.setdefault(connector.id, object()),
        )

    async def probe(self, connector: Connector) -> ProbeResult:
        """The scripted probe result."""
        return self.probe_result


class FakeLoader:
    """Implements `RoutingLoader` over the world; counts the reads."""

    def __init__(self, world: ConnectorWorld) -> None:
        """Keep the world."""
        self.world = world

    async def load(self) -> RoutingSnapshot:
        """A copy of the stored rows."""
        self.world.loads += 1
        return RoutingSnapshot(
            connectors=dict(self.world.connectors), routes=dict(self.world.routes)
        )


def with_secret(connector: Connector, last4: str = "wxyz") -> Connector:
    """A row that holds a key."""
    return replace(connector, has_secret=True, secret_last4=last4)
