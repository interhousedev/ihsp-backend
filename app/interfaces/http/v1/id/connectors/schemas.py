"""Schemas of the MCP connector endpoints."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.identity.application.get_mcp_scopes import ServerCatalog
from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.ports.mcp_call_log import McpCallEntry
from app.shared.actor import Role

from pydantic import BaseModel, Field

Server = Literal["student", "lms", "admin", "teacher"]
McpOutcome = Literal["ok", "denied", "rate_limited", "not_found", "invalid", "error"]


class ConnectorResponse(BaseModel):
    """Connector."""

    id: UUID
    name: str
    server: Server
    scopes: list[str]
    extra_scopes: list[str]
    course_ids: list[UUID] | None
    kind: Literal["token", "oauth"]
    token_prefix: str | None
    created_at: datetime | None
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def of(cls, connector: McpConnector) -> "ConnectorResponse":
        """Map a connector."""
        return cls(
            id=connector.id,
            name=connector.name,
            server=connector.server,
            scopes=connector.scopes,
            extra_scopes=connector.extra_scopes,
            course_ids=connector.course_ids,
            kind=connector.kind,
            token_prefix=connector.token_prefix,
            created_at=connector.created_at,
            last_used_at=connector.last_used_at,
            expires_at=connector.expires_at,
            revoked_at=connector.revoked_at,
        )


class CreateConnectorBody(BaseModel):
    """POST /v1/id/me/connectors."""

    server: Server
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1)
    course_ids: list[UUID] | None = None
    expires_in_days: int
    otp_code: str | None = Field(default=None, max_length=16)


class NewConnectorResponse(BaseModel):
    """The connector and its token, shown once."""

    connector: ConnectorResponse
    token: str


class ScopeResponse(BaseModel):
    """One scope and its tools."""

    scope: str
    tools: list[str]


class PresetResponse(BaseModel):
    """A named set of scopes."""

    key: str
    scopes: list[str]


class ServerCatalogResponse(BaseModel):
    """One server of the scope catalog."""

    server: Server
    roles: list[Role]
    scopes: list[ScopeResponse]
    presets: list[PresetResponse]

    @classmethod
    def of(cls, catalog: ServerCatalog) -> "ServerCatalogResponse":
        """Map a catalog entry."""
        return cls(
            server=catalog.server,
            roles=catalog.roles,
            scopes=[
                ScopeResponse(scope=s.scope, tools=list(s.tools))
                for s in catalog.scopes
            ],
            presets=[
                PresetResponse(key=p.key, scopes=list(p.scopes))
                for p in catalog.presets
            ],
        )


class ScopeCatalogResponse(BaseModel):
    """ScopeCatalog."""

    servers: list[ServerCatalogResponse]


class ScopeOfferResponse(BaseModel):
    """New permissions offered for the caller's connectors; holds no token."""

    id: UUID
    release_id: str
    server: Server
    read_scopes: list[str]
    write_scopes: list[str]
    connector_names: list[str]
    expires_at: datetime


class ScopeOfferDecisionBody(BaseModel):
    """POST /v1/id/me/connectors/offers/{offer_id}/decision."""

    grant: bool


class ScopeOfferDecisionResponse(BaseModel):
    """How it ended: someone else's offer and an unknown one answer the same."""

    result: Literal[
        "granted", "declined", "already_decided", "expired", "not_available"
    ]
    connector_names: list[str]


class McpActivityItem(BaseModel):
    """One MCP tool call: redacted arguments, counts, never content."""

    id: UUID
    created_at: datetime
    connector_id: UUID | None
    connector_name: str | None
    client_id: str | None
    server: Server
    tool: str
    scope: str
    read_only: bool
    outcome: McpOutcome
    error_code: str | None
    error_id: str | None
    duration_ms: int
    arguments: dict[str, Any] | None
    result_summary: dict[str, Any] | None
    ip: str | None

    @classmethod
    def of(cls, entry: McpCallEntry) -> "McpActivityItem":
        """Map a stored trace."""
        return cls(
            id=entry.id,
            created_at=entry.created_at,
            connector_id=entry.connector_id,
            connector_name=entry.connector_name,
            client_id=entry.client_id,
            server=entry.server,
            tool=entry.tool,
            scope=entry.scope,
            read_only=entry.read_only,
            outcome=entry.outcome,
            error_code=entry.error_code,
            error_id=entry.error_id,
            duration_ms=entry.duration_ms,
            arguments=entry.arguments,
            result_summary=entry.result_summary,
            ip=entry.ip,
        )


class McpActivityPage(BaseModel):
    """A page of the caller's calls."""

    items: list[McpActivityItem]
    next_cursor: str | None
