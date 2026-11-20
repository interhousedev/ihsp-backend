"""Request and response models of the connector and pipeline routes (admin only)."""

from datetime import datetime
from typing import Literal

from app.modules.ai.application.connectors import PipelineView
from app.modules.ai.domain.connectors import (
    Connector,
    ConnectorKind,
    EffectiveRoute,
    ProbeResult,
)

from pydantic import BaseModel, ConfigDict, Field, SecretStr

Effort = Literal["none", "minimal", "low", "medium", "high"]


class ConnectorOut(BaseModel):
    """A connector; the key is never returned, only whether one is stored."""

    id: str
    kind: ConnectorKind
    title: str
    base_url: str | None
    enabled: bool
    has_secret: bool
    secret_last4: str | None
    builtin: bool
    source: Literal["env", "db"]

    @classmethod
    def of(cls, connector: Connector) -> "ConnectorOut":
        """Build from the domain connector."""
        return cls(
            id=connector.id,
            kind=connector.kind,
            title=connector.title,
            base_url=connector.base_url,
            enabled=connector.enabled,
            has_secret=connector.has_secret,
            secret_last4=connector.secret_last4,
            builtin=connector.builtin,
            source=connector.source,
        )


class ConnectorsResponse(BaseModel):
    """GET /connectors."""

    items: list[ConnectorOut]
    kinds: list[ConnectorKind]


class ConnectorBody(BaseModel):
    """POST /connectors: a new connector; the key goes to Vault."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=48, description="Slug: a-z, 0-9, _ and -.")
    kind: ConnectorKind
    title: str = Field(max_length=120)
    base_url: str | None = Field(
        default=None, max_length=500, description="Required for openai_compatible."
    )
    api_key: SecretStr | None = Field(default=None, description="Write-only.")
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Extra headers (openai_compatible), write-only.",
    )


class ConnectorPatchBody(BaseModel):
    """PATCH /connectors/{id}: only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    api_key: SecretStr | None = Field(default=None, description="Write-only.")


class ConnectorTestOut(BaseModel):
    """POST /connectors/{id}/test."""

    ok: bool
    latency_ms: int
    error: str | None

    @classmethod
    def of(cls, result: ProbeResult) -> "ConnectorTestOut":
        """Build from the probe result."""
        return cls(ok=result.ok, latency_ms=result.latency_ms, error=result.error)


class PipelineRouteBody(BaseModel):
    """PUT /pipelines/{pipeline}: each field null falls through to the environment."""

    model_config = ConfigDict(extra="forbid")

    connector_id: str | None = Field(default=None, max_length=48)
    model: str | None = Field(default=None, max_length=255)
    reasoning_effort: Effort | None = None


class RouteOut(BaseModel):
    """The runtime route of a pipeline."""

    connector_id: str | None
    model: str | None
    reasoning_effort: str | None
    updated_at: datetime | None


class EffectiveOut(BaseModel):
    """What the calls of a pipeline use now."""

    connector_id: str
    model: str
    reasoning_effort: str | None
    source: Literal["runtime", "env"]

    @classmethod
    def of(cls, route: EffectiveRoute) -> "EffectiveOut":
        """Build from the effective route."""
        return cls(
            connector_id=route.connector_id,
            model=route.model,
            reasoning_effort=route.reasoning_effort,
            source=route.source,
        )


class EnvDefaultOut(BaseModel):
    """What the pipeline uses without a runtime route."""

    connector_id: str
    model: str
    reasoning_effort: str | None


class PipelineOut(BaseModel):
    """One pipeline with its tasks and routes."""

    pipeline: str
    tasks: list[str]
    route: RouteOut
    effective: EffectiveOut
    env_default: EnvDefaultOut

    @classmethod
    def of(cls, view: PipelineView) -> "PipelineOut":
        """Build from the application view."""
        route = view.route
        return cls(
            pipeline=view.pipeline.value,
            tasks=view.tasks,
            route=RouteOut(
                connector_id=route.connector_id if route else None,
                model=route.model if route else None,
                reasoning_effort=route.reasoning_effort if route else None,
                updated_at=route.updated_at if route else None,
            ),
            effective=EffectiveOut.of(view.effective),
            env_default=EnvDefaultOut(
                connector_id=view.env_default.connector_id,
                model=view.env_default.model,
                reasoning_effort=view.env_default.reasoning_effort,
            ),
        )


class PipelinesResponse(BaseModel):
    """GET /pipelines."""

    items: list[PipelineOut]
