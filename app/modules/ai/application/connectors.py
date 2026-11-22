"""Administrators' work on connectors and pipeline routes (audited, applied at once).

Keys go to Vault first and the row follows; the database and the API never hold or
return a key (only `has_secret` and the last four characters). Connectors made from
the environment are shown and can be overridden by a row; deleting the row returns
them to the environment.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.modules.ai.application.routing import RouteService
from app.modules.ai.domain.connectors import (
    BUILTIN_IDS,
    EFFORTS,
    PIPELINE_OF,
    TRACING_CAPTURE_DEFAULT,
    Connector,
    ConnectorKind,
    EffectiveRoute,
    Pipeline,
    PipelineRoute,
    ProbeResult,
    default_tracing,
    kind_fits,
    valid_base_url,
    valid_slug,
)
from app.modules.ai.domain.errors import (
    ConnectorExistsError,
    ConnectorInUseError,
    ConnectorInvalidError,
    ConnectorKindMismatchError,
    ConnectorNotFoundError,
    PipelineNotFoundError,
)
from app.modules.ai.ports.connectors import (
    ConnectorRuntime,
    ConnectorSecrets,
    ConnectorUnitOfWork,
)
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft

AUDIT_CONNECTOR_ADDED = "admin.ai_connector_added"
AUDIT_CONNECTOR_UPDATED = "admin.ai_connector_updated"
AUDIT_CONNECTOR_REMOVED = "admin.ai_connector_removed"
AUDIT_PIPELINE_ROUTED = "admin.ai_pipeline_routed"
_MIN_KEY_FOR_LAST4 = 8
_MAX_TITLE = 120
_MAX_URL = 500
_MAX_MODEL = 255


def _last4(api_key: str) -> str | None:
    """The last four characters of a long enough key (a short key shows nothing)."""
    return api_key[-4:] if len(api_key) >= _MIN_KEY_FOR_LAST4 else None


def _order(connector: Connector) -> tuple[int, str]:
    known = BUILTIN_IDS.index(connector.id) if connector.id in BUILTIN_IDS else 99
    return known, connector.id


class ConnectorAdmin:
    """Lists, adds, changes, removes and tests connectors."""

    def __init__(
        self,
        uow_factory: Callable[[], ConnectorUnitOfWork],
        secrets: ConnectorSecrets,
        runtime: ConnectorRuntime,
        routing: RouteService,
        *,
        allow_plain_local_urls: bool,
    ) -> None:
        """Keep the transaction factory, the key store, the clients and the router."""
        self.uow_factory = uow_factory
        self.secrets = secrets
        self.runtime = runtime
        self.routing = routing
        self._plain_local = allow_plain_local_urls

    async def list(self, actor: Actor) -> list[Connector]:
        """Every connector: the environment's, replaced by rows of the same id."""
        async with self.uow_factory() as uow:
            rows = await uow.connectors.list()
        found = self.runtime.builtins()
        found.update({row.id: row for row in rows})
        return sorted(found.values(), key=_order)

    async def create(
        self,
        actor: Actor,
        *,
        id: str,
        kind: ConnectorKind,
        title: str,
        base_url: str | None,
        api_key: str | None,
        headers: Mapping[str, str] | None,
    ) -> Connector:
        """Add a connector; its key is written to Vault before the row."""
        if not valid_slug(id):
            raise ConnectorInvalidError(params={"field": "id"})
        base_url = self._checked_url(kind, base_url)
        title = self._checked_title(title)
        async with self.uow_factory() as uow:
            if id in self.runtime.builtins() or await uow.connectors.get(id):
                raise ConnectorExistsError()
            secret = _secret(api_key, headers)
            if secret:
                await self.secrets.put(id, secret)
            connector = Connector(
                id=id,
                kind=kind,
                title=title,
                base_url=base_url,
                enabled=True,
                has_secret=bool(secret),
                secret_last4=_last4(api_key) if api_key else None,
                builtin=False,
                source="db",
            )
            try:
                await uow.connectors.add(connector, actor.user_id)
                uow.audit(_audit(AUDIT_CONNECTOR_ADDED, actor, connector))
                await uow.commit()
            except Exception:
                if secret:
                    await self.secrets.delete(id)
                raise
        self.routing.forget_clients(id)
        return connector

    async def update(
        self,
        actor: Actor,
        id: str,
        *,
        title: str | None = None,
        base_url: str | None = None,
        enabled: bool | None = None,
        api_key: str | None = None,
    ) -> Connector:
        """Change a connector; a connector of the environment gets an override row."""
        async with self.uow_factory() as uow:
            row = await uow.connectors.get(id)
            current = row or self.runtime.builtins().get(id)
            if current is None:
                raise ConnectorNotFoundError()
            changes: dict[str, Any] = {}
            if title is not None:
                changes["title"] = self._checked_title(title)
            if base_url is not None:
                changes["base_url"] = self._checked_url(current.kind, base_url)
            if enabled is not None:
                changes["enabled"] = enabled
            if api_key:
                await self.secrets.put(id, _secret(api_key, None) or {})
                changes["has_secret"] = True
                changes["secret_last4"] = _last4(api_key)
            updated = replace(current, **changes, source="db")
            if updated.kind is ConnectorKind.OPENAI_COMPATIBLE and not updated.base_url:
                raise ConnectorInvalidError(params={"field": "base_url"})
            if row is None:
                await uow.connectors.add(updated, actor.user_id)
            else:
                await uow.connectors.update(updated)
            uow.audit(
                _audit(AUDIT_CONNECTOR_UPDATED, actor, updated, fields=sorted(changes))
            )
            await uow.commit()
        self.routing.forget_clients(id)
        return updated

    async def delete(self, actor: Actor, id: str) -> None:
        """Remove a connector and its key; a built-in one only loses its override."""
        async with self.uow_factory() as uow:
            row = await uow.connectors.get(id)
            if row is None:
                if id in self.runtime.builtins():
                    return
                raise ConnectorNotFoundError()
            used = [
                r.pipeline.value
                for r in await uow.routes.list()
                if r.connector_id == id
            ]
            if used:
                raise ConnectorInUseError(params={"pipelines": ", ".join(sorted(used))})
            if row.has_secret:
                await self.secrets.delete(id)
            await uow.connectors.delete(id)
            uow.audit(_audit(AUDIT_CONNECTOR_REMOVED, actor, row))
            await uow.commit()
        self.routing.forget_clients(id)

    async def test(self, actor: Actor, id: str) -> ProbeResult:
        """Ask the provider something tiny; the answer never contains the key."""
        found = next((c for c in await self.list(actor) if c.id == id), None)
        if found is None:
            raise ConnectorNotFoundError()
        return await self.runtime.probe(found)

    def _checked_title(self, title: str) -> str:
        title = title.strip()
        if not title or len(title) > _MAX_TITLE:
            raise ConnectorInvalidError(params={"field": "title"})
        return title

    def _checked_url(self, kind: ConnectorKind, base_url: str | None) -> str | None:
        base_url = (base_url or "").strip() or None
        if base_url is None:
            if kind is ConnectorKind.OPENAI_COMPATIBLE:
                raise ConnectorInvalidError(params={"field": "base_url"})
            return None
        if len(base_url) > _MAX_URL or not valid_base_url(
            base_url, allow_plain_local=self._plain_local
        ):
            raise ConnectorInvalidError(params={"field": "base_url"})
        return base_url.rstrip("/")


def _secret(api_key: str | None, headers: Mapping[str, str] | None) -> dict[str, Any]:
    secret: dict[str, Any] = {}
    if api_key:
        secret["api_key"] = api_key
    if headers:
        secret["headers"] = dict(headers)
    return secret


def _audit(
    kind: str, actor: Actor, connector: Connector, **extra: object
) -> AuditDraft:
    # the key never reaches the audit log
    return AuditDraft(
        type=kind,
        actor_id=actor.user_id,
        metadata={"id": connector.id, "kind": connector.kind.value, **extra},
    )


@dataclass(frozen=True, slots=True)
class PipelineView:
    """A pipeline, its tasks, its runtime route and what its calls use."""

    pipeline: Pipeline
    tasks: list[str]
    route: PipelineRoute | None
    effective: EffectiveRoute
    env_default: EffectiveRoute
    tracing_enabled: bool
    capture_content: bool
    tracing_default: bool


class PipelineAdmin:
    """Shows and changes the runtime routes of the pipelines."""

    def __init__(
        self,
        uow_factory: Callable[[], ConnectorUnitOfWork],
        runtime: ConnectorRuntime,
        routing: RouteService,
        clock: Clock,
    ) -> None:
        """Keep the transaction factory, the environment connectors and the router."""
        self.uow_factory = uow_factory
        self.runtime = runtime
        self.routing = routing
        self.clock = clock

    async def list(self, actor: Actor) -> list[PipelineView]:
        """Every pipeline with its tasks and routes."""
        async with self.uow_factory() as uow:
            routes = {r.pipeline: r for r in await uow.routes.list()}
        self.routing.invalidate()
        return [await self._view(p, routes.get(p)) for p in Pipeline]

    async def put(
        self,
        actor: Actor,
        pipeline: str,
        *,
        connector_id: str | None,
        model: str | None,
        reasoning_effort: str | None,
        tracing_enabled: bool | None = None,
        capture_content: bool | None = None,
    ) -> PipelineView:
        """Route a pipeline; every field empty removes the route.

        `tracing_enabled` and `capture_content` null mean the default: admission
        untraced, the rest traced, content per the environment.
        """
        found = _pipeline(pipeline)
        model = (model or "").strip() or None
        if model is not None and len(model) > _MAX_MODEL:
            raise ConnectorInvalidError(params={"field": "model"})
        if reasoning_effort is not None and reasoning_effort not in EFFORTS:
            raise ConnectorInvalidError(params={"field": "reasoning_effort"})
        async with self.uow_factory() as uow:
            if connector_id is not None:
                rows = {c.id: c for c in await uow.connectors.list()}
                known = {**self.runtime.builtins(), **rows}.get(connector_id)
                if known is None:
                    raise ConnectorNotFoundError()
                if not kind_fits(known.kind, found):
                    raise ConnectorKindMismatchError()
            route = PipelineRoute(
                pipeline=found,
                connector_id=connector_id,
                model=model,
                reasoning_effort=reasoning_effort,
                updated_at=self.clock.now(),
                updated_by=actor.user_id,
                tracing_enabled=tracing_enabled,
                capture_content=capture_content,
            )
            if route.empty:
                await uow.routes.delete(found)
            else:
                await uow.routes.put(route)
            uow.audit(_route_audit(actor, route))
            await uow.commit()
        self.routing.invalidate()
        return await self._view(found, None if route.empty else route)

    async def delete(self, actor: Actor, pipeline: str) -> None:
        """Send the pipeline back to the environment's values."""
        found = _pipeline(pipeline)
        async with self.uow_factory() as uow:
            await uow.routes.delete(found)
            uow.audit(_route_audit(actor, PipelineRoute(found, None, None, None)))
            await uow.commit()
        self.routing.invalidate()

    async def _view(
        self, pipeline: Pipeline, route: PipelineRoute | None
    ) -> PipelineView:
        tasks = sorted(t.value for t, p in PIPELINE_OF.items() if p is pipeline)
        traced = route.tracing_enabled if route else None
        capture = route.capture_content if route else None
        return PipelineView(
            pipeline=pipeline,
            tasks=tasks,
            route=route,
            effective=await self.routing.route_of(pipeline),
            env_default=self.routing.env_route(pipeline),
            tracing_enabled=default_tracing(pipeline) if traced is None else traced,
            capture_content=TRACING_CAPTURE_DEFAULT if capture is None else capture,
            tracing_default=default_tracing(pipeline),
        )


def _pipeline(name: str) -> Pipeline:
    try:
        return Pipeline(name)
    except ValueError:
        raise PipelineNotFoundError() from None


def _route_audit(actor: Actor, route: PipelineRoute) -> AuditDraft:
    return AuditDraft(
        type=AUDIT_PIPELINE_ROUTED,
        actor_id=actor.user_id,
        metadata={
            "pipeline": route.pipeline.value,
            "connector_id": route.connector_id,
            "model": route.model,
            "reasoning_effort": route.reasoning_effort,
            "tracing_enabled": route.tracing_enabled,
            "capture_content": route.capture_content,
        },
    )
